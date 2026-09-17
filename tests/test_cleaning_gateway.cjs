// Behavioral tests of Apps Script coordinator without Google/Resend access.
const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict'), crypto=require('node:crypto');
const context={console, Date, PropertiesService:{getScriptProperties:()=>({getProperties:()=>({TOKEN_SECRET:'test-secret',APP_URL:'https://example.com',RESEND_API_KEY:'test',MAIL_FROM:'Chalupa <sender@example.com>',MAIL_REPLY_TO:'owner@example.com'})})},
  Utilities:{getUuid:()=>crypto.randomUUID(), base64EncodeWebSafe:x=>Buffer.from(x).toString('base64url'),
    computeHmacSha256Signature:(x,key)=>crypto.createHmac('sha256',key).update(x).digest(),
    base64DecodeWebSafe:x=>Buffer.from(x,'base64url'),newBlob:x=>({getDataAsString:()=>x.toString()}),
    formatDate:()=> '2030-01-01 10:00:00',computeDigest:(_,x)=>crypto.createHash('sha256').update(x).digest(),DigestAlgorithm:{SHA_256:'sha256'}},
  SpreadsheetApp:{flush(){}}, LockService:{getScriptLock:()=>({waitLock(){},releaseLock(){}})}};
vm.createContext(context);vm.runInContext(fs.readFileSync('integrations/cleaning.gs','utf8'),context);
let db;
function fixture(){
 db={Rezervace:{header:['Jméno','Příjmení','email','Datum - Start','Datum - Konec','Stav','ID','Vytvořeno','Cena celkem','Úklid - e-mail'],rows:[['Host','Test','guest@example.com','2030-01-02','2030-01-05','Čeká na potvrzení','stay','timestamp',5000,'']]},
 'Úklid':{header:['Jméno','E-mail','E-mailing','Odhlášeno dne'],rows:[['Firma A','a@example.com','',''],['Firma B','b@example.com','',''],['Odhlášený','off@example.com','Odhlášeno','']]},
 'Nabídky úklidu':{header:['ID nabídky','ID rezervace','Datum úklidu','Vytvořeno'],rows:[]},
 'Historie rezervací':{header:['Čas (Praha)','ID události','ID rezervace','Událost','Zdroj','Původní hodnoty','Nové hodnoty'],rows:[]},
 'E-maily úklidu':{header:['ID zprávy','ID nabídky','E-mail','Stav','První pokus','Resend ID','Obsah'],rows:[]}};
 context.table_=(name)=>{const t=db[name];return {...t,sheet:{getSheetId:()=>Object.keys(db).indexOf(name),getRange:(r,c)=>({setValue(v){t.rows[r-2]??=[];t.rows[r-2][c-1]=v;},getValue(){return t.rows[r-2]?.[c-1]||'';},setValues(v){for(let i=0;i<v.length;i++){t.rows[r-2+i]??=[];v[i].forEach((x,j)=>t.rows[r-2+i][c-1+j]=x);}}}),getLastRow:()=>t.rows.length+1,appendRow:r=>t.rows.push(r),deleteRow:r=>t.rows.splice(r-2,1)}};};
}
context.book_=()=>({getId:()=> 'test-book'});
context.Sheets={Spreadsheets:{batchUpdate:({requests})=>{
  const next=JSON.parse(JSON.stringify(db));
  for(const q of requests){
    const op=q.updateCells||q.appendCells||q.deleteDimension;
    const range=op.range;
    const t=next[Object.keys(next)[range?range.sheetId:op.sheetId]];
    if(q.updateCells) op.rows.forEach((r,i)=>r.values.forEach((v,j)=>{t.rows[range.startRowIndex-1+i][range.startColumnIndex+j]=v.userEnteredValue.stringValue??v.userEnteredValue.numberValue;}));
    if(q.appendCells) t.rows.push(...op.rows.map(r=>r.values.map(v=>v.userEnteredValue.stringValue??v.userEnteredValue.numberValue)));
    if(q.deleteDimension) t.rows.splice(range.startIndex-1,range.endIndex-range.startIndex);
  }
  db=next;
}}};
const run=q=>context.dispatch_(q), token=(kind,email)=>context.encode_({kind,email,offer:db['Nabídky úklidu'].rows[0]?.[0]});
fixture();run({action:'status',id:'stay',status:'Zaplaceno'});
assert.equal(db['E-maily úklidu'].rows.length,2);assert.equal(db['Nabídky úklidu'].rows.length,1);
run({action:'status',id:'stay',status:'Čeká na potvrzení'});run({action:'status',id:'stay',status:'Zaplaceno'});assert.equal(db['E-maily úklidu'].rows.length,2);
const a=token('claim','a@example.com'), b=token('claim','b@example.com');
run({action:'inspect',token:a});assert.equal(db.Rezervace.rows[0][9],'');
run({action:'claim',token:a});run({action:'claim',token:a});assert.equal(db.Rezervace.rows[0][9],'a@example.com');
assert.throws(()=>run({action:'claim',token:b}),/jiný tým/);
run({action:'unsubscribe',token:token('unsubscribe','a@example.com')});
assert.equal(db['Úklid'].rows[0][2],'Odhlášeno');assert.equal(db.Rezervace.rows[0][9],'a@example.com');
assert.throws(()=>run({action:'claim',token:a+'bad'}),/Neplatný/);
fixture();run({action:'status',id:'stay',status:'Zaplaceno'});const stale=token('claim','a@example.com');db.Rezervace.rows[0][4]='2030-01-06';assert.throws(()=>run({action:'claim',token:stale}),/aktuální/);
fixture();run({action:'status',id:'stay',status:'Zaplaceno'});const sent=[];
context.UrlFetchApp={fetch:(url,opts)=>{sent.push(opts);return{getResponseCode:()=>200,getContentText:()=>JSON.stringify({id:'sent'})}}};
run({action:'unsubscribe',token:token('unsubscribe','b@example.com')});context.processQueue();assert.equal(sent.length,1);assert.equal(JSON.parse(sent[0].payload).to[0],'a@example.com');assert.match(JSON.parse(sent[0].payload).html,/Odhlásit z e-mailingu/);context.processQueue();assert.equal(sent.length,1);
assert.equal(JSON.parse(sent[0].payload).from, 'Chalupa <sender@example.com>');
assert.equal(JSON.parse(sent[0].payload).reply_to, 'owner@example.com');
fixture();run({action:'status',id:'stay',status:'Zaplaceno'});run({action:'assign',id:'stay',email:'a@example.com'});context.processQueue();assert.equal(sent.length,1);
console.log('Gateway: paid transition, deduplication, first claimant, unsubscribe, stale/tampered links and queue checks passed.');

fixture();run({action:'status',id:'stay',status:'Zaplaceno'});
assert.equal(db['Historie rezervací'].rows.length,1);
run({action:'status',id:'stay',status:'Zaplaceno'});
assert.equal(db['Historie rezervací'].rows.length,1);
run({action:'claim',token:token('claim','a@example.com')});
assert.equal(db['Historie rezervací'].rows.length,2);
assert.match(db['Historie rezervací'].rows[1][4],/Osobní odkaz/);
run({action:'delete',id:'stay'});run({action:'delete',id:'stay'});
assert.equal(db['Historie rezervací'].rows.length,3);
assert.equal(JSON.parse(db['Historie rezervací'].rows[2][5])['Úklid - e-mail'],'a@example.com');
assert.equal(db.Rezervace.rows.length,0);
fixture();db['Historie rezervací'].rows=Array.from({length:1000},(_,i)=>['',String(i)]);
run({action:'status',id:'stay',status:'Zaplaceno'});
assert.equal(db['Historie rezervací'].rows.length,1000);
assert.equal(db['Historie rezervací'].rows[0][1],'1');
fixture();const apply=context.Sheets.Spreadsheets.batchUpdate;
context.Sheets.Spreadsheets.batchUpdate=()=>{throw new Error('API failed')};
assert.throws(()=>run({action:'delete',id:'stay'}),/API failed/);
assert.equal(db.Rezervace.rows.length,1);assert.equal(db['Historie rezervací'].rows.length,0);
context.Sheets.Spreadsheets.batchUpdate=apply;
console.log('History: atomic status/claim/delete, no-op deduplication, deletion snapshot and 1000-row retention passed.');
