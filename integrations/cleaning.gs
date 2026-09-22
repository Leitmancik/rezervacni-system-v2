/** Koordinátor nabídek úklidu. Všechny zápisy z této integrace používají jeden ScriptLock.
 * Nastavení v Script Properties: SHEET_ID, APP_URL, API_SECRET, TOKEN_SECRET, RESEND_API_KEY, MAIL_FROM, MAIL_REPLY_TO.
 * Spustit setup(), nasadit webovou aplikaci, poté nastavit Streamlit cleaning_mail.
 */
const PAID = 'Zaplaceno';
const STATUSES = ['Čeká na potvrzení', 'Potvrzeno - čeká na zaplacení', PAID];
const OFFER_HEADERS = ['ID nabídky', 'ID rezervace', 'Datum úklidu', 'Vytvořeno'];
const MAIL_HEADERS = ['ID zprávy', 'ID nabídky', 'E-mail', 'Stav', 'První pokus', 'Resend ID', 'Obsah'];
function properties_() { return PropertiesService.getScriptProperties().getProperties(); }
function locked_(fn) {
  const lock = LockService.getScriptLock();
  lock.waitLock(25000);
  try { return fn(); } finally { lock.releaseLock(); }
}
function book_() { return SpreadsheetApp.openById(properties_().SHEET_ID); }
function table_(name, headers, create) {
  const book = book_();
  let sheet = book.getSheetByName(name);
  if (!sheet && create) sheet = book.insertSheet(name);
  if (!sheet) throw new Error('Chybí list ' + name + '.');
  let data = sheet.getDataRange().getDisplayValues();
  if (!data.some(row => row.some(Boolean)) && create) {
    sheet.getRange(1, 1, 1, headers.length).setValues([headers]); data = [headers.slice()];
  }
  if (headers.some((h, i) => data[0][i] !== h)) throw new Error('Neočekávané sloupce listu ' + name + '.');
  return {sheet, header: data[0], rows: data.slice(1)};
}
function column_(t, name, create) {
  if (t.header.filter(h => h === name).length > 1) throw new Error('Duplicitní sloupec ' + name);
  let index = t.header.indexOf(name);
  if (index < 0 && create) {
    index = Math.max(t.header.length, ...t.rows.map(r => r.length));
    if (index >= t.sheet.getMaxColumns()) t.sheet.insertColumnsAfter(t.sheet.getMaxColumns(), index + 1 - t.sheet.getMaxColumns());
    t.sheet.getRange(1, index + 1).setValue(name); t.header[index] = name;
  }
  if (index < 0) throw new Error('Chybí sloupec ' + name + '. Spusťte setup.');
  return index;
}
function unique_(t, index, value, insensitive) {
  const normalize = v => insensitive ? String(v || '').trim().toLowerCase() : String(v || '').trim();
  const matches = t.rows.map((row, i) => ({row, number: i + 2})).filter(r => normalize(r.row[index]) === normalize(value));
  if (!value || matches.length !== 1) throw new Error('Záznam nebyl jednoznačně nalezen.');
  return matches[0];
}
function reservations_() { return table_('Rezervace', ['Jméno', 'Příjmení', 'email', 'Datum - Start', 'Datum - Konec', 'Stav', 'ID', 'Vytvořeno', 'Cena celkem']); }
function contacts_() { return table_('Úklid', ['Jméno', 'E-mail']); }
function active_(t, person) { return !person.row[column_(t, 'E-mailing')] || person.row[column_(t, 'E-mailing')] === 'Přihlášeno'; }
function isoDate_(text) {
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return text;
  const m = /^(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})$/.exec(text);
  if (!m) throw new Error('Neplatný termín úklidu.');
  return `${m[3]}-${m[2].padStart(2, '0')}-${m[1].padStart(2, '0')}`;
}
function beforeDeadline_(day) {
  return Utilities.formatDate(new Date(), 'Europe/Prague', 'yyyy-MM-dd HH:mm:ss') < day + ' 11:00:00';
}
function setup() {
  return locked_(() => {
    const p = properties_();
    for (const key of ['SHEET_ID', 'APP_URL', 'API_SECRET', 'TOKEN_SECRET', 'RESEND_API_KEY', 'MAIL_FROM', 'MAIL_REPLY_TO']) if (!p[key]) throw new Error('Chybí nastavení ' + key);
    if (!p.APP_URL.startsWith('https://') || p.API_SECRET.length < 32 || p.TOKEN_SECRET.length < 32) throw new Error('Neplatné nastavení služby.');
    const c = contacts_(); column_(c, 'E-mailing', true); column_(c, 'Odhlášeno dne', true);
    column_(reservations_(), 'Úklid - e-mail', true);
    setupHistory_();
    table_('Nabídky úklidu', OFFER_HEADERS, true); table_('E-maily úklidu', MAIL_HEADERS, true);
    if (!ScriptApp.getProjectTriggers().some(t => t.getHandlerFunction() === 'processQueue')) ScriptApp.newTrigger('processQueue').timeBased().everyMinutes(1).create();
    return 'Připraveno; existující zaplacené pobyty se zpětně nerozesílají.';
  });
}
function doPost(e) {
  let result;
  try {
    const request = JSON.parse(e.postData.contents);
    const secret = properties_().API_SECRET;
    if (!secret || request.secret !== secret) throw new Error('Neplatné oprávnění.');
    result = locked_(() => dispatch_(request));
    result.ok = true;
  } catch (error) { result = {ok: false, message: error.publicMessage || 'Operaci nelze dokončit. Ověřte konfiguraci a platnost odkazu.'}; }
  return ContentService.createTextOutput(JSON.stringify(result)).setMimeType(ContentService.MimeType.JSON);
}
function reject_(message) { const e = new Error(message); e.publicMessage = message; throw e; }
function dispatch_(q) {
  if(q.require_billing && (typeof billingEnabled_ !== 'function' || !billingEnabled_())) reject_('Fakturace není aktivovaná v koordinátoru.');
  if(q.action.startsWith('billing_')) {
    if(typeof billingDispatch_ !== 'function' || !billingEnabled_()) reject_('Fakturace není aktivovaná v koordinátoru.');
    return billingDispatch_(q);
  }
  if (q.action === 'status') {
    if (!STATUSES.includes(q.status)) reject_('Neplatný stav rezervace.');
    const t = reservations_(), r = unique_(t, 6, q.id);
    if(q.status === STATUSES[1] && typeof billingEnabled_ === 'function' && billingEnabled_()) billingEnqueue_(t,r);
    // Nejdříve připravíme idempotentní frontu. Do zaplacení ji worker neodešle.
    if (q.status === PAID && r.row[5] !== PAID && properties_().RESEND_API_KEY && !r.row[column_(t, 'Úklid - e-mail')]) enqueue_(r);
    historyChange_(t, r, {5:q.status}, 'Aplikace · bez přihlášení');
    SpreadsheetApp.flush(); return {};
  }
  if (q.action === 'delete') {
    const t = reservations_(), matches = t.rows.filter(r => r[6] === q.id);
    if (matches.length > 1) reject_('ID rezervace není jedinečné.');
    if (matches.length) historyChange_(t, unique_(t, 6, q.id), null, 'Aplikace · bez přihlášení');
    SpreadsheetApp.flush(); return {};
  }
  if (q.action === 'assign') {
    const t = reservations_(), r = unique_(t, 6, q.id);
    let email = '';
    if (q.email) email = unique_(contacts_(), 1, q.email, true).row[1];
    historyChange_(t, r, {[column_(t, 'Úklid - e-mail')]:email}, 'Aplikace · bez přihlášení');
    SpreadsheetApp.flush(); return {};
  }
  const token = decode_(q.token);
  const contacts = contacts_(), person = unique_(contacts, 1, token.email, true);
  if (token.kind === 'unsubscribe') {
    if (q.action === 'unsubscribe') {
      contacts.sheet.getRange(person.number, column_(contacts, 'E-mailing') + 1).setValue('Odhlášeno');
      const cell = contacts.sheet.getRange(person.number, column_(contacts, 'Odhlášeno dne') + 1);
      if (!cell.getValue()) cell.setValue(new Date().toISOString());
      SpreadsheetApp.flush(); return {};
    }
    if (q.action === 'inspect') return {kind: token.kind};
    reject_('Odkaz není určený k přihlášení.');
  }
  if (!['inspect', 'claim'].includes(q.action) || token.kind !== 'claim') reject_('Neplatná operace.');
  const offers = table_('Nabídky úklidu', OFFER_HEADERS), offer = unique_(offers, 0, token.offer);
  const mail = table_('E-maily úklidu', MAIL_HEADERS);
  if (!mail.rows.some(r => r[1] === token.offer && r[2].toLowerCase() === token.email.toLowerCase())) reject_('Odkaz není platný.');
  const t = reservations_(), r = unique_(t, 6, offer.row[1]), index = column_(t, 'Úklid - e-mail');
  const day = isoDate_(r.row[4]);
  if (r.row[5] !== PAID || day !== offer.row[2] || !beforeDeadline_(day)) reject_('Nabídka už není aktuální.');
  if (!active_(contacts, person)) reject_('Tento kontakt je odhlášený z nabídek úklidu.');
  if (r.row[index] && r.row[index].toLowerCase() !== person.row[1].toLowerCase()) reject_('Tento úklid již převzal jiný tým.');
  if (q.action === 'claim') {
    historyChange_(t, r, {[index]:person.row[1]}, 'Osobní odkaz úklidu · '+person.row[1]); SpreadsheetApp.flush();
  }
  return {kind: 'claim', name: person.row[0], date: day.split('-').reverse().join('. ')};
}
function encode_(payload) {
  const data = Utilities.base64EncodeWebSafe(JSON.stringify(payload));
  return data + '.' + Utilities.base64EncodeWebSafe(Utilities.computeHmacSha256Signature(data, properties_().TOKEN_SECRET));
}
function decode_(token) {
  if (typeof token !== 'string' || token.length > 4000) reject_('Neplatný odkaz.');
  const parts = token.split('.');
  if (parts.length !== 2 || parts[1] !== Utilities.base64EncodeWebSafe(Utilities.computeHmacSha256Signature(parts[0], properties_().TOKEN_SECRET))) reject_('Neplatný odkaz.');
  return JSON.parse(Utilities.newBlob(Utilities.base64DecodeWebSafe(parts[0])).getDataAsString());
}
function escape_(s) { return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c])); }
function email_(offer, person) {
  const config = properties_();
  if (!config.MAIL_FROM || !config.MAIL_REPLY_TO) throw new Error('Chybí nastavení MAIL_FROM nebo MAIL_REPLY_TO.');
  const base = config.APP_URL.replace(/\/$/, '') + '/?cleaning_token=';
  const claim = base + encodeURIComponent(encode_({kind:'claim', email:person[1], offer:offer[0]}));
  const unsubscribe = base + encodeURIComponent(encode_({kind:'unsubscribe', email:person[1]}));
  const date = offer[2].split('-').reverse().join('. ');
  const tasks = ['Sundat povlečení', 'Vysát / vytřít podlahy', 'Uklidit nádobí a myčku', 'Vypustit, vyčistit a napustit vířivku', 'Uklidit krb', 'Uklidit venkovní posezení'];
  const warning = 'Přihlášení je závazné. Pokud přijatý úklid neprovedete včas a podle stanoveného standardu, budete odebráni ze seznamu úklidových týmů.';
  return {from:config.MAIL_FROM, to:[person[1]], reply_to:config.MAIL_REPLY_TO,
    subject:`Nabídka úklidu chalupy – ${date} – odměna 2 500 Kč`,
    text:`Dobrý den, ${person[0]},\n\nNabízíme úklid chalupy dne ${date} mezi 11:00 a 15:00 (český čas). Úklid musí být dokončen do 15:00.\nOdměna za celý úklid: 2 500 Kč.\n\n${tasks.map(t => '- '+t).join('\n')}\n\n${warning}\n\nZávazně přihlásit k úklidu: ${claim}\nOdhlásit z e-mailingu: ${unsubscribe}`,
    html:`<div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;color:#234d40"><h1>Úklid chalupy Vernířovice</h1><p>Dobrý den, ${escape_(person[0])},</p><p>Nabízíme úklid dne <b>${date}, 11:00–15:00</b> (český čas). Úklid musí být dokončen do 15:00.</p><h2>Odměna 2 500 Kč</h2><ul>${tasks.map(t=>'<li>'+t+'</li>').join('')}</ul><p>${warning}</p><p><a style="display:inline-block;padding:16px;background:#234d40;color:white;border-radius:8px" href="${escape_(claim)}">Závazně přihlásit k úklidu</a></p><p>Na otevřené stránce své přihlášení potvrdíte. Termín získá první tým, který jej přijme.</p><p><a href="${escape_(unsubscribe)}">Odhlásit z e-mailingu</a></p></div>`};
}
function enqueue_(reservation) {
  const day = isoDate_(reservation.row[4]);
  if (!beforeDeadline_(day)) return;
  const offers = table_('Nabídky úklidu', OFFER_HEADERS);
  let offer = offers.rows.find(r => r[1] === reservation.row[6]);
  if (offer) return; // Jedna nabídka na rezervaci, včetně opakovaného přepnutí stavů.
  const contacts = contacts_();
  const people = contacts.rows.filter(row => row[1] && active_(contacts, {row}));
  offer = [Utilities.getUuid(), reservation.row[6], day, new Date().toISOString()];
  const queue = table_('E-maily úklidu', MAIL_HEADERS);
  // Fronta před markerem nabídky: při pádu se existující řádky dohledají podle ID rezervace.
  const existing = queue.rows.find(row => row[0].startsWith(reservation.row[6] + ':'));
  if (existing) offer[0] = existing[1];
  const seen = new Set(queue.rows.map(r => r[0]));
  const additions = [];
  for (const person of people) {
    const id = reservation.row[6] + ':' + person[1].toLowerCase();
    if (seen.has(id)) continue;
    seen.add(id);
    additions.push([id, offer[0], person[1], 'Čeká', '', '', JSON.stringify(email_(offer, person))]);
  }
  if (additions.length) queue.sheet.getRange(queue.sheet.getLastRow()+1, 1, additions.length, MAIL_HEADERS.length).setValues(additions);
  offers.sheet.appendRow(offer); SpreadsheetApp.flush();
}
function processQueue() {
  return locked_(() => {
    const q = table_('E-maily úklidu', MAIL_HEADERS), offers = table_('Nabídky úklidu', OFFER_HEADERS);
    let count = 0;
    for (let i=0; i<q.rows.length && count<5; i++) {
      const row = q.rows[i];
      if (!['Čeká', 'Odesílá se'].includes(row[3])) continue;
      count++;
      const state = value => q.sheet.getRange(i+2, 4).setValue(value);
      const offer = offers.rows.find(r => r[0] === row[1]);
      if (!offer) continue;
      const t = reservations_(), contact = contacts_();
      let r, person;
      try { r=unique_(t,6,offer[1]); person=unique_(contact,1,row[2],true); } catch (_) { state('Zrušeno'); continue; }
      if (!active_(contact, person) || r.row[5] !== PAID || r.row[column_(t,'Úklid - e-mail')] || isoDate_(r.row[4]) !== offer[2] || !beforeDeadline_(offer[2])) { state('Zrušeno'); continue; }
      // Resend deduplikuje jen 24 hodin. Nejasný starý pokus nikdy neopakujeme automaticky.
      if (row[4] && Date.now()-Date.parse(row[4]) > 23*3600*1000) { state('Nutná kontrola'); continue; }
      if (!row[4]) q.sheet.getRange(i+2,5).setValue(new Date().toISOString());
      state('Odesílá se'); SpreadsheetApp.flush();
      try {
        const response = UrlFetchApp.fetch('https://api.resend.com/emails', {method:'post', contentType:'application/json',
          headers:{Authorization:'Bearer '+properties_().RESEND_API_KEY, 'Idempotency-Key':'cleaning/'+row[1]+'/'+Utilities.base64EncodeWebSafe(Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,row[0]))}, payload:row[6], muteHttpExceptions:true});
        const code = response.getResponseCode();
        if (code >= 200 && code < 300) {
          const id = JSON.parse(response.getContentText()).id;
          if (!id) throw new Error('Missing id');
          q.sheet.getRange(i+2,6).setValue(id); state('Odesláno');
        } else if (code === 429 || code >= 500) { /* další pokus přes trigger se stejným klíčem */ }
        else { state('Chyba '+code); }
      } catch (_) { /* nejistý výsledek; stejný obsah a idempotency key při opakování */ }
      SpreadsheetApp.flush();
    }
  });
}

// Atomický zápis změny rezervace a historie přes Google Sheets API.
const HISTORY_HEADERS = ['Čas (Praha)', 'ID události', 'ID rezervace', 'Událost', 'Zdroj', 'Původní hodnoty', 'Nové hodnoty'];
const HISTORY_LIMIT = 1000;
function historyCells_(values) {
  return values.map(v=>({userEnteredValue:typeof v==='number'?{numberValue:v}:{stringValue:String(v)}}));
}
function historySnapshot_(t, row) {
  const result={}; t.header.forEach((name,i)=>{if(name) result[name]=String(row[i]??'');}); return result;
}
function historyEvent_(id, kind, source, before, after) {
  return [Utilities.formatDate(new Date(),'Europe/Prague',"yyyy-MM-dd'T'HH:mm:ss.SSSXXX"), Utilities.getUuid(), id, kind, source, JSON.stringify(before), JSON.stringify(after)];
}
function historyBatch_(requests, events) {
  const h=table_('Historie rezervací',HISTORY_HEADERS,true);
  const sheetId=h.sheet.getSheetId();
  if(events.length) requests.push({appendCells:{sheetId,rows:events.map(e=>({values:historyCells_(e)})),fields:'userEnteredValue'}});
  const extra=h.rows.length+events.length-HISTORY_LIMIT;
  if(extra>0) requests.push({deleteDimension:{range:{sheetId,dimension:'ROWS',startIndex:1,endIndex:extra+1}}});
  if(requests.length) Sheets.Spreadsheets.batchUpdate({requests},book_().getId());
}
function historyChange_(t,r,changes,source) {
  let before={},after={},requests=[];
  const sheetId=t.sheet.getSheetId(), rowIndex=r.number-1;
  if(changes===null) {
    before=historySnapshot_(t,r.row);
    requests.push({deleteDimension:{range:{sheetId,dimension:'ROWS',startIndex:rowIndex,endIndex:rowIndex+1}}});
  } else {
    for(const [i,value] of Object.entries(changes)) {
      if(String(r.row[i]??'')===String(value)) continue;
      before[t.header[i]]=String(r.row[i]??''); after[t.header[i]]=String(value);
      requests.push({updateCells:{range:{sheetId,startRowIndex:rowIndex,endRowIndex:rowIndex+1,startColumnIndex:Number(i),endColumnIndex:Number(i)+1},rows:[{values:historyCells_([value])}],fields:'userEnteredValue'}});
    }
    if(!requests.length) return;
  }
  historyBatch_(requests,[historyEvent_(r.row[6],changes===null?'Smazání':'Změna',source,before,after)]);
}
function setupHistory_() {
  const h=table_('Historie rezervací',HISTORY_HEADERS,true);
  h.sheet.setFrozenRows(1);
  h.sheet.getRange(1,1,1,HISTORY_HEADERS.length).setFontWeight('bold').setBackground('#234D40').setFontColor('#ffffff');
  h.sheet.setColumnWidths(1,1,215); h.sheet.setColumnWidths(2,2,230);
  h.sheet.setColumnWidths(4,2,200); h.sheet.setColumnWidths(6,2,400);
  if(!h.rows.length) {
    const t=reservations_();
    historyBatch_([],t.rows.filter(r=>r[6]).map(r=>historyEvent_(r[6],'Výchozí stav','Aktivace historie',{},historySnapshot_(t,r))));
  }
}
