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

vm.runInContext(fs.readFileSync('integrations/billing.gs','utf8'),context);
let props, external, calls, fail, clock;
const oldFixture=fixture;
function reset() {
 oldFixture();
 db.Rezervace.header.push('Fakturační údaje');
 db.Rezervace.rows[0].push(JSON.stringify({street:'Testovací 12',city:'Praha',zip:'11000',country:'CZ',on_company:false}));
 db['Faktury rezervací']={header:['ID úlohy','Data'],rows:[]};
 props={SHEET_ID:'test',API_SECRET:'x'.repeat(32),FAKTUROID_SLUG:'test',FAKTUROID_CLIENT_ID:'client',FAKTUROID_CLIENT_SECRET:'secret',
 FAKTUROID_USER_AGENT:'Test (test@example.com)',FAKTUROID_BANK_ACCOUNT_ID:'1',FAKTUROID_NON_VAT_PAYER:'true',FAKTUROID_ENABLED:'true'};
 context.PropertiesService={getScriptProperties:()=>({getProperties:()=>props,getProperty:k=>props[k],setProperty:(k,v)=>{props[k]=v;}})};
 external={subjects:[],invoices:[]};calls=[];fail=null;clock='2030-01-01 10:00:00';
 context.Utilities.formatDate=(_,__,fmt)=>fmt==='yyyy-MM-dd'?clock.slice(0,10):clock;
 context.billingApi_=(method,path,body)=>{
  calls.push({method,path,body});
  if(fail && fail.path===path && !fail.after){const e=new Error('network');e.code=fail.code;fail=null;throw e;}
  let result={};
  if(path==='account.json')return{vat_mode:'non_vat_payer'};
  if(path.includes('?custom_id=')){const resource=path.split('.')[0],id=decodeURIComponent(path.split('=')[1]);return external[resource].filter(r=>r.custom_id===id);}
  if(method==='post' && path==='subjects.json'){result={...body,id:external.subjects.length+1};external.subjects.push(result);}
  else if(method==='post' && path==='invoices.json'){
   result={...body,id:external.invoices.length+100,number:'2026-001',total:body.lines[0].unit_price,remaining_amount:body.related_id?0:body.lines[0].unit_price,status:'open',html_url:'https://app.fakturoid.cz/test/invoices/100'};
   external.invoices.push(result);
   if(body.related_id)external.invoices.find(i=>i.id===body.related_id).related_id=result.id;
  } else if(path.endsWith('/message.json')){const id=Number(path.split('/')[1]);external.invoices.find(i=>i.id===id).sent_at='2030-01-01T10:00:00';}
  else if(method==='get' && path.startsWith('invoices/')) result=external.invoices.find(i=>i.id===Number(path.split('/')[1].split('.')[0]));
  if(fail && fail.path===path && fail.after){fail=null;throw new Error('lost response');}
  return JSON.parse(JSON.stringify(result));
 };
}
const approve=()=>context.dispatch_({action:'status',id:'stay',status:'Potvrzeno - čeká na zaplacení'});
const jobs=()=>context.billingJobs_();
const work=()=>{for(const j of jobs()){j.next_attempt=0;context.billingSave_(j);}context.processInvoices();};
const posts=p=>calls.filter(c=>c.method==='post'&&c.path===p).length;
reset();
assert.equal(jobs().length,0);approve();approve();assert.equal(jobs().length,1);
assert.equal(jobs()[0].vs,'9000000001');assert.equal(external.invoices.length,0);
work();work();assert.equal(external.invoices.length,1);assert.equal(posts('invoices/100/message.json'),1);
assert.equal(external.invoices[0].document_type,'proforma');assert.equal(external.invoices[0].proforma_followup_document,'final_invoice');
assert.equal(jobs()[0].state,'Odesláno');assert.equal(external.invoices[0].lines[0].unit_price,'5000.00');
assert.equal(external.invoices[0].subject_id,1);assert.equal(external.subjects[0].name,'Host Test');
assert.throws(()=>context.billingDispatch_({action:'billing_details',id:'stay',billing:{}}),/připravena/);
clock='2030-01-05 10:59:59';external.invoices[0].status='paid';work();assert.equal(jobs().length,1);
clock='2030-01-05 11:00:00';work();assert.equal(jobs().length,2);work();work();
assert.equal(external.invoices.length,2);assert.equal(external.invoices[1].document_type,'invoice');
assert.equal(external.invoices[1].related_id,100);assert.equal(jobs()[1].state,'Odesláno');
assert.equal(posts('invoices/101/message.json'),1);
reset();approve();fail={path:'invoices.json',after:true};work();assert.equal(jobs()[0].state,'Vystavování');work();
assert.equal(posts('invoices.json'),1);assert.equal(jobs()[0].state,'Odesláno');
reset();approve();fail={path:'invoices.json'};work();work();work();assert.equal(posts('invoices.json'),1);assert.equal(external.invoices.length,0);
assert.equal(jobs()[0].state,'Vystavování');
reset();approve();fail={path:'subjects.json',after:true};work();work();assert.equal(posts('subjects.json'),1);assert.equal(external.invoices.length,1);
reset();approve();fail={path:'invoices/100/message.json',after:true};work();work();assert.equal(posts('invoices/100/message.json'),1);assert.equal(jobs()[0].state,'Odesláno');
reset();approve();fail={path:'invoices/100/message.json'};work();work();assert.equal(posts('invoices/100/message.json'),1);assert.equal(jobs()[0].state,'Odesílání');
reset();approve();fail={path:'invoices.json',code:429};work();work();assert.equal(external.invoices.length,1);assert.equal(jobs()[0].state,'Odesláno');
reset();approve();fail={path:'invoices.json',code:422};work();work();assert.equal(posts('invoices.json'),1);assert.equal(jobs()[0].state,'Chyba');
context.billingDispatch_({action:'billing_retry',id:'stay'});work();assert.equal(external.invoices.length,1);
reset();approve();context.dispatch_({action:'status',id:'stay',status:'Čeká na potvrzení'});work();assert.equal(external.invoices.length,0);approve();work();assert.equal(external.invoices.length,1);
reset();approve();context.dispatch_({action:'delete',id:'stay'});work();assert.equal(external.invoices.length,0);assert.equal(jobs().length,1);
reset();db.Rezervace.rows[0][8]='';assert.throws(approve,/cenu/);assert.equal(jobs().length,0);
reset();db.Rezervace.rows[0][10]='';assert.throws(approve,/adresu/);assert.equal(db.Rezervace.rows[0][5],'Čeká na potvrzení');
reset();db.Rezervace.rows[0][10]=JSON.stringify({street:'Firma 1',city:'Brno',zip:'60200',country:'CZ',on_company:true,company:'Firma s.r.o.',registration_no:'12345678',vat_no:'CZ12345678'});approve();work();assert.equal(external.subjects[0].name,'Firma s.r.o.');assert.equal(external.subjects[0].registration_no,'12345678');
reset();approve();work();clock='2030-01-05 11:00:00';work();assert.equal(jobs().length,1);assert.match(jobs()[0].error,/uhrazení/);
reset();approve();db.Rezervace.rows[0][8]=6000;work();assert.equal(external.invoices.length,0);assert.match(jobs()[0].error,/změnily/);
reset();approve();work();external.invoices[0].status='paid';clock='2030-01-05 11:00:00';work();fail={path:'invoices.json',after:true};work();work();assert.equal(external.invoices.length,2);assert.equal(posts('invoices.json'),2);assert.equal(jobs()[1].state,'Odesláno');
console.log('Billing: approval, customer/company, exact prices, VS, retries, lost responses, rejection, cancellation and checkout settlement passed.');

reset();props.FAKTUROID_ENABLED='false';assert.throws(()=>context.dispatch_({action:'status',id:'stay',status:'Potvrzeno - čeká na zaplacení',require_billing:true}),/aktivovaná/);assert.equal(jobs().length,0);
reset();approve();context.billingApi_=()=>({vat_mode:'vat_payer'});work();assert.equal(jobs()[0].invoice_id,undefined);
reset();approve();db.Rezervace.rows.push([...db.Rezervace.rows[0]]);db.Rezervace.rows[1][6]='stay-2';
context.dispatch_({action:'status',id:'stay-2',status:'Potvrzeno - čeká na zaplacení'});assert.equal(jobs()[1].vs,'9000000002');
console.log('Billing: disabled coordinator, VAT-mode mismatch and unique reservation numbers passed.');
