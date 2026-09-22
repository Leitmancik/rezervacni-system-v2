/** Fakturoid API v3. Přidat do STEJNÉHO projektu jako cleaning.gs.
 * setupBilling() jen připraví úložiště a trigger. Aktivace: FAKTUROID_ENABLED=true.
 * Fronta přežije zavření aplikace, restart i smazání rezervace. Nikdy ji nemažte.
 */
const BILLING_HEADERS = ['ID úlohy', 'Data'];
const BILLING_COLUMN = 'Fakturační údaje';
function billingEnabled_() { return properties_().FAKTUROID_ENABLED === 'true'; }
function billingConfig_() {
  const p = properties_();
  for (const k of ['SHEET_ID','API_SECRET','FAKTUROID_SLUG','FAKTUROID_CLIENT_ID','FAKTUROID_CLIENT_SECRET','FAKTUROID_USER_AGENT','FAKTUROID_BANK_ACCOUNT_ID'])
    if (!p[k]) reject_('Chybí nastavení fakturace: ' + k);
  if (!/^[a-zA-Z0-9_-]+$/.test(p.FAKTUROID_SLUG) || !/^[1-9]\d*$/.test(p.FAKTUROID_BANK_ACCOUNT_ID) || p.API_SECRET.length < 32)
    reject_('Neplatné nastavení fakturace.');
  // Zvolený proces je určen neplátci; při změně režimu vyžaduje úpravu.
  if (p.FAKTUROID_NON_VAT_PAYER !== 'true') reject_('Potvrďte nastavení neplátce DPH.');
  return p;
}
function setupBilling() {
  return locked_(() => {
    billingConfig_();
    column_(reservations_(), BILLING_COLUMN, true);
    table_('Faktury rezervací', BILLING_HEADERS, true);
    setupHistory_();
    if (!ScriptApp.getProjectTriggers().some(t => t.getHandlerFunction() === 'processInvoices'))
      ScriptApp.newTrigger('processInvoices').timeBased().everyMinutes(1).create();
    return 'Připraveno. Historické rezervace se automaticky nefakturují.';
  });
}
function billingTable_() { return table_('Faktury rezervací', BILLING_HEADERS); }
function billingJobs_() { return billingTable_().rows.filter(r => r[0]).map(r => JSON.parse(r[1])); }
function billingSave_(job) {
  const t = billingTable_(), matches = t.rows.map((r,i)=>({r,i})).filter(x=>x.r[0]===job.key);
  if(matches.length > 1) reject_('Duplicitní úloha fakturace.');
  if(matches.length) t.sheet.getRange(matches[0].i+2,2).setValue(JSON.stringify(job));
  else t.sheet.appendRow([job.key,JSON.stringify(job)]);
  SpreadsheetApp.flush();
}
function billingDetails_(d) {
  if (!d || typeof d !== 'object') reject_('Doplňte fakturační údaje rezervace.');
  const clean = {};
  for(const k of ['street','city','zip','country','company','registration_no','vat_no']) {
    clean[k] = String(d[k] || '').trim();
    if(clean[k].length > 200) reject_('Fakturační údaj je příliš dlouhý.');
  }
  clean.on_company = d.on_company === true;
  if(!clean.street || !clean.city || !clean.zip || !/^[A-Z]{2}$/.test(clean.country)) reject_('Doplňte úplnou fakturační adresu.');
  if(['CZ','SK'].includes(clean.country) && !/^\d{3}\s?\d{2}$/.test(clean.zip)) reject_('Zkontrolujte PSČ.');
  if(clean.on_company) {
    if(!clean.company || !clean.registration_no || (clean.country === 'CZ' && !/^\d{8}$/.test(clean.registration_no))) reject_('Doplňte název firmy a platné IČO.');
  } else { clean.company = ''; clean.registration_no = ''; clean.vat_no = ''; }
  return clean;
}
function billingAmount_(v) {
  let text = String(v).replace(/Kč|[\s\u00a0]/g,'');
  if(/^\d{1,3}(\.\d{3})+$/.test(text)) text=text.replace(/\./g,'');
  const n = Number(text.replace(',','.'));
  if(!text || !Number.isFinite(n) || n <= 0) reject_('Před schválením doplňte kladnou celkovou cenu rezervace.');
  return n.toFixed(2);
}
function billingEnqueue_(t,r) {
  billingConfig_();
  const key = r.row[6] + ':advance';
  if(billingJobs_().some(j=>j.key===key)) return;
  const d = billingDetails_(JSON.parse(r.row[column_(t,BILLING_COLUMN)] || '{}'));
  if(!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(r.row[2])) reject_('Neplatný e-mail hosta.');
  const amount = billingAmount_(r.row[8]);
  const p = PropertiesService.getScriptProperties();
  // Vyhrazená číselná řada pro rezervace; pod společným ScriptLockem, nikdy resetovat.
  const vs = Math.max(Number(p.getProperty('BILLING_LAST_VS') || 9000000000), ...billingJobs_().map(j=>Number(j.vs))) + 1;
  if(!Number.isSafeInteger(vs) || vs > 9999999999) reject_('Číselná řada rezervací je vyčerpaná.');
  p.setProperty('BILLING_LAST_VS',String(vs));
  billingSave_({key,rid:r.row[6],kind:'advance',vs:String(vs),state:'Čeká',
    date_from:isoDate_(r.row[3]),date_to:isoDate_(r.row[4]),amount,email:r.row[2],
    subject:{name:d.on_company?d.company:[r.row[0],r.row[1]].join(' '),email:r.row[2],street:d.street,city:d.city,zip:d.zip,country:d.country,
      registration_no:d.registration_no,vat_no:d.vat_no,type:'customer',custom_id:'chalupa:'+r.row[6]},
    approved_at:new Date().toISOString()});
}
function billingDispatch_(q) {
  if(q.action==='billing_list') {
    const jobs={};
    for(const j of billingJobs_()) if(j.kind==='advance') jobs[j.rid]={state:j.state,vs:j.vs,number:j.number,url:j.url,error:j.error};
    for(const j of billingJobs_()) if(j.kind==='final' && jobs[j.rid]) jobs[j.rid].final={state:j.state,number:j.number,url:j.url,error:j.error};
    return {jobs};
  }
  if(q.action==='billing_details') {
    if(billingJobs_().some(j=>j.rid===q.id)) reject_('Fakturace už byla připravena. Údaje dokladu upravte ve Fakturoidu.');
    const t=reservations_(),r=unique_(t,6,q.id),d=billingDetails_(q.billing);
    historyChange_(t,r,{[column_(t,BILLING_COLUMN)]:JSON.stringify(d)},'Fakturační údaje · majitel');
    return {};
  }
  if(q.action==='billing_retry') {
    const jobs=billingJobs_().filter(j=>j.rid===q.id && j.state!=='Odesláno');
    for(const j of jobs) {
      // Při nejasném výsledku pouze dohledáváme, neopakujeme POST.
      if(j.state==='Chyba') j.state='Čeká';
      j.next_attempt=0;j.error='';billingSave_(j);
    }
    return {};
  }
  reject_('Neplatná operace fakturace.');
}
function billingToken_(p) {
  const cache=CacheService.getScriptCache(),key='fakturoid-token:'+p.FAKTUROID_SLUG;
  const cached=cache.get(key);if(cached)return cached;
  const r=UrlFetchApp.fetch('https://app.fakturoid.cz/api/v3/oauth/token',{
    method:'post',contentType:'application/json',muteHttpExceptions:true,
    headers:{Authorization:'Basic '+Utilities.base64Encode(p.FAKTUROID_CLIENT_ID+':'+p.FAKTUROID_CLIENT_SECRET),'User-Agent':p.FAKTUROID_USER_AGENT,Accept:'application/json'},
    payload:JSON.stringify({grant_type:'client_credentials'})});
  if(r.getResponseCode()!==200) throw new Error('Přístup k Fakturoidu se nepodařilo ověřit.');
  const data=JSON.parse(r.getContentText());if(!data.access_token)throw new Error('Chybí token.');
  cache.put(key,data.access_token,Math.min(7000,Number(data.expires_in)-60));return data.access_token;
}
function billingApi_(method,path,body) {
  const p=billingConfig_();
  const options={method,contentType:'application/json',muteHttpExceptions:true,
    headers:{Authorization:'Bearer '+billingToken_(p),'User-Agent':p.FAKTUROID_USER_AGENT,Accept:'application/json'}};
  if(body!==undefined)options.payload=JSON.stringify(body);
  const r=UrlFetchApp.fetch('https://app.fakturoid.cz/api/v3/accounts/'+p.FAKTUROID_SLUG+'/'+path,options),code=r.getResponseCode();
  if(code<200||code>=300){const e=new Error('Fakturoid HTTP '+code);e.code=code;throw e;}
  return code===204?{}:JSON.parse(r.getContentText());
}
function billingFind_(resource,id) {
  const result=billingApi_('get',resource+'.json?custom_id='+encodeURIComponent(id));
  if(!Array.isArray(result))throw new Error('Neplatná odpověď API.');
  const matches=result.filter(x=>x.custom_id===id);
  if(matches.length>1)throw new Error('Duplicitní externí ID.');
  return matches[0];
}
function billingPayload_(job) {
  const p=billingConfig_();
  const payload={custom_id:'chalupa:'+job.key,subject_id:job.subject_id,document_type:job.kind==='advance'?'proforma':'invoice',
    variable_symbol:job.vs,order_number:job.vs,currency:'CZK',language:'cz',payment_method:'bank',
    bank_account_id:Number(p.FAKTUROID_BANK_ACCOUNT_ID),hide_bank_account:false,
    issued_on:Utilities.formatDate(new Date(),'Europe/Prague','yyyy-MM-dd'),
    vat_price_mode:'from_total_with_vat',round_total:false,
    lines:[{name:'Ubytování na chalupě '+job.date_from+' – '+job.date_to,quantity:'1',unit_name:'pobyt',unit_price:job.amount,vat_rate:0}]};
  if(job.kind==='advance') payload.proforma_followup_document='final_invoice';
  else payload.related_id=job.advance_id;
  return payload;
}
function billingWriteApi_(job,phase,path,payload) {
  // Marker trvale uložit PŘED síťovým požadavkem; pád poté znamená nejistý výsledek.
  job.state=phase;billingSave_(job);
  try {return billingApi_('post',path,payload);}
  catch(e){
    // Definitivně odmítnuté zápisy lze opravit/opakovat; timeout a 5xx jen dohledat.
    if(e.code>=400 && e.code<500 && ![408,409].includes(e.code))job.state=e.code===429?'Čeká':'Chyba';
    throw e;
  }
}
function billingProcess_(job) {
  const t=reservations_(),matches=t.rows.filter(r=>r[6]===job.rid);
  if(matches.length!==1 || ![STATUSES[1],PAID].includes(matches[0][5]))return;
  const r=matches[0];
  if(isoDate_(r[3])!==job.date_from || isoDate_(r[4])!==job.date_to || billingAmount_(r[8])!==job.amount) {
    job.error='Termín nebo cena se změnily. Zkontrolujte fakturaci ručně.';billingSave_(job);return;
  }
  if(job.kind==='final' && !billingCheckout_(job))return;
  const account=billingApi_('get','account.json');
  if(account.vat_mode!=='non_vat_payer')throw new Error('Účet Fakturoidu není nastaven jako neplátce DPH.');
  const subjectCustom='chalupa:'+job.rid;
  if(!job.subject_id) {
    let subject=billingFind_('subjects',subjectCustom);
    if(!subject) {
      if(job.state==='Zakládání kontaktu')throw new Error('Výsledek založení kontaktu není jistý.');
      subject=billingWriteApi_(job,'Zakládání kontaktu','subjects.json',job.subject);
    }
    if(!subject.id)throw new Error('Chybí ID kontaktu.');
    job.subject_id=subject.id;job.state='Čeká';billingSave_(job);
  }
  if(!job.invoice_id) {
    let invoice=billingFind_('invoices','chalupa:'+job.key);
    if(!invoice) {
      if(job.state==='Vystavování')throw new Error('Výsledek vystavení není jistý.');
      if(!job.payload){job.payload=billingPayload_(job);billingSave_(job);}
      invoice=billingWriteApi_(job,'Vystavování','invoices.json',job.payload);
    }
    if(!invoice.id)throw new Error('Chybí ID faktury.');
    job.invoice_id=invoice.id;job.number=invoice.number;job.url=invoice.html_url;job.state='Vystaveno';billingSave_(job);
  }
  const invoice=billingApi_('get','invoices/'+job.invoice_id+'.json');
  if(invoice.custom_id!=='chalupa:'+job.key || String(invoice.variable_symbol)!==job.vs ||
      invoice.document_type!==(job.kind==='advance'?'proforma':'invoice') || invoice.currency!=='CZK' ||
      Math.abs(Number(invoice.total)-Number(job.amount))>0.005 || ['cancelled','uncollectible'].includes(invoice.status))
    throw new Error('Faktura neodpovídá schválené rezervaci.');
  if(job.kind==='final' && (Number(invoice.remaining_amount)!==0 || invoice.related_id!==job.advance_id))
    throw new Error('Na vyúčtování není správně odečtená uhrazená záloha.');
  if(invoice.sent_at){job.state='Odesláno';job.error='';billingSave_(job);return;}
  if(job.state==='Odesílání')throw new Error('Výsledek odeslání není jistý. Ověřte jej ve Fakturoidu.');
  billingWriteApi_(job,'Odesílání','invoices/'+job.invoice_id+'/message.json',{
    email:job.email,email_copy:'',subject:job.kind==='advance'?'Záloha k rezervaci '+job.vs:'Vyúčtování pobytu '+job.vs,
    message:job.kind==='advance'?'Dobrý den,\n\nvaše rezervace byla schválena. Zálohovou fakturu s QR platbou najdete zde: #link#\nVariabilní symbol: #vs#\nČástka: #price#\nSplatnost: #due#\n\nDěkujeme.':'Dobrý den,\n\nděkujeme za pobyt. Zasíláme vyúčtovací fakturu s odečtenou uhrazenou zálohou: #link#\nNic dalšího neplaťte.',
    replace_with_defaults:false,deliver_now:true});
  job.state='Odesláno';job.error='';billingSave_(job);
}
function billingCheckout_(job) {
  return Utilities.formatDate(new Date(),'Europe/Prague','yyyy-MM-dd HH:mm:ss') >= job.date_to+' 11:00:00';
}
function billingFinal_(advance) {
  if(!billingCheckout_(advance))return;
  const key=advance.rid+':final';if(billingJobs_().some(j=>j.key===key))return;
  const t=reservations_(),r=t.rows.filter(r=>r[6]===advance.rid);
  if(r.length!==1 || ![STATUSES[1],PAID].includes(r[0][5]))return;
  if(isoDate_(r[0][3])!==advance.date_from || isoDate_(r[0][4])!==advance.date_to || billingAmount_(r[0][8])!==advance.amount)return;
  const invoice=billingApi_('get','invoices/'+advance.invoice_id+'.json');
  if(invoice.status!=='paid' || invoice.currency!=='CZK' || Math.abs(Number(invoice.total)-Number(advance.amount))>0.005) {
    advance.error='Vyúčtování čeká na úplné uhrazení zálohy ve Fakturoidu.';billingSave_(advance);return;
  }
  // Ručně vytvořenou návaznou fakturu nepřepisujeme a nevystavujeme druhou.
  if(invoice.related_id) {advance.error='Navazující doklad už existuje ve Fakturoidu; zkontrolujte jej ručně.';billingSave_(advance);return;}
  billingSave_({key,rid:advance.rid,kind:'final',vs:advance.vs,state:'Čeká',date_from:advance.date_from,date_to:advance.date_to,
    amount:advance.amount,email:advance.email,subject_id:advance.subject_id,advance_id:advance.invoice_id});
  advance.error='';billingSave_(advance);
}
function processInvoices() {
  if(!billingEnabled_())return;
  return locked_(()=>{
    billingConfig_();
    const jobs=billingJobs_(),now=Date.now();let count=0;
    for(const job of jobs.sort((a,b)=>(a.next_attempt||0)-(b.next_attempt||0))) {
      if(count>=3)break;
      if(job.next_attempt>now || job.state==='Chyba')continue;
      if(job.state==='Odesláno' && (job.kind==='final' || !billingCheckout_(job) || jobs.some(j=>j.key===job.rid+':final')))continue;
      count++;
      try {
        if(job.state==='Odesláno')billingFinal_(job);else billingProcess_(job);
        job.attempts=0;
      } catch(e) {
        job.attempts=(job.attempts||0)+1;
        job.error=e.code?'Fakturoid odmítl požadavek (HTTP '+e.code+'). Zkontrolujte nastavení.':'Zpracování vyžaduje ověření ve Fakturoidu. Nejisté vystavení ani odeslání se neopakuje naslepo.';
      }
      job.next_attempt=now+(job.state==='Odesláno'?3600000:Math.min(3600000,60000*Math.pow(2,job.attempts||0)));
      billingSave_(job);
    }
  });
}

/** Ruční diagnostika spojení. Nevystavuje doklady ani neposílá e-maily. */
function verifyBillingConnection() {
  return locked_(() => {
    const account = billingApi_('get', 'account.json');
    const banks = billingApi_('get', 'bank_accounts.json');
    const bankId = Number(billingConfig_().FAKTUROID_BANK_ACCOUNT_ID);
    if (account.vat_mode !== 'non_vat_payer') throw new Error('Účet není nastaven jako neplátce DPH.');
    if (!banks.some(bank => bank.id === bankId)) throw new Error('Nastavený bankovní účet nebyl nalezen.');
    console.log('Fakturoid připojen. Režim: neplátce DPH. Bankovní účet nalezen. Žádné doklady ani e-maily nebyly vytvořeny.');
  });
}
