# Aktivace nabídek úklidu

Implementace je připravená, ale ve výchozím stavu nic neodesílá.

## Resend

Ověřte svou odesílací doménu v Resendu a nastavte DNS podle aktuálních hodnot
z jeho administračního rozhraní. Odesílací adresa nemusí mít vlastní schránku;
pro odpovědi nastavte existující adresu v MAIL_REPLY_TO.

Klíč Resendu omezte na odesílání z ověřené domény a uložte přímo do Script
Properties. Klíče ani skutečné kontaktní adresy nevkládejte do repozitáře.

## Koordinátor v Google Apps Script
Vytvořit samostatný Apps Script projekt pro Codex aplikaci a vložit cleaning.gs.
Nepřepisovat skript původní aplikace Claude. Webová aplikace i minutový trigger
musí patřit ke stejnému projektu, aby sdílely ScriptLock.

Script Properties:
- SHEET_ID: ID_SPOLECNE_GOOGLE_TABULKY
- APP_URL: HTTPS_ADRESA_NOVE_APLIKACE
- API_SECRET: náhodný tajný řetězec alespoň 32 znaků
- TOKEN_SECRET: jiný náhodný tajný řetězec alespoň 32 znaků
- RESEND_API_KEY: omezený Resend klíč
- MAIL_FROM: jméno a ověřená odesílací adresa, např. Chalupa <sender@example.com>
- MAIL_REPLY_TO: kontaktní adresa pro odpovědi, např. owner@example.com

Spustit setup() a autorizovat potřebný přístup k tabulce a odesílacímu API.
setup pouze připraví sloupce/listy a minutový trigger; neodesílá historické pobyty.
Nasadit jako webovou aplikaci vykonávanou pod vlastníkem projektu. Endpoint musí
být dosažitelný ze Streamlit serveru bez Google přihlášení; každá operace je
ověřená API_SECRET. Samotná znalost URL neumožňuje číst ani měnit data.
Resend API klíč a oba tajné řetězce zůstávají výhradně v nastavení.

V Streamlit Secrets přidat [cleaning_mail] podle vzoru, url finálního /exec
nasazení, shodné API_SECRET do secret a enabled = true. Stejné nastavení použít
pro případnou lokální práci se skutečnými daty. Po změně kódu Apps Script vydat
novou verzi existujícího nasazení; nestačí uložit editor.

## Změny tabulky
- Úklid: stávající Jméno a E-mail zůstávají; na konci přibudou E-mailing a
  Odhlášeno dne. Prázdný E-mailing znamená Přihlášeno kvůli původním kontaktům.
  Odhlášeno = vynechat další nabídky, zachovat kontaktní historii a převzaté úklidy.
- Rezervace: používá se existující Úklid - e-mail, dohledaný podle hlavičky.
- Nabídky úklidu: ID nabídky, ID rezervace, Datum úklidu, Vytvořeno.
- E-maily úklidu: ID zprávy, ID nabídky, E-mail, Stav, První pokus, Resend ID, Obsah.
  Obsah je uložený payload pro přesně stejné opakování nejistých odeslání.
  Obsahuje osobní odkazy: nesdílet tuto tabulku veřejně.
Původní data a další sloupce se nemažou ani neposouvají. Při opakovaném setup
nedochází k resetu odhlášení ani k duplicitě triggeru.

## Chování
Změna stavu na Zaplaceno připraví jednu nabídku pro dosud nepřiřazený budoucí
úklid a jednu zprávu pro každý přihlášený unikátní e-mail. Opakované přepnutí
nevytváří další nabídku. Zpětná rozesílka historických zaplacených pobytů se
neprovádí. Frontu průběžně posílá minutový trigger, nejvýše pět zpráv v běhu.

Tlačítko e-mailu otevře Streamlit s podepsaným osobním odkazem. Načtení odkazu
nic nemění. Teprve potvrzení přiřadí kontakt pod společným zámkem. Druhý tým
nemůže přepsat první. Kontroluje se aktuální zaplacení, datum odjezdu, existence
kontaktu, odhlášení a uzávěrka v 11:00 v den úklidu. Změněné datum zneplatní
původní nabídku. Již přiřazený tým nebo zrušená rezervace zabrání dalšímu odesílání.
Samostatné tlačítko Odhlásit z e-mailingu po potvrzení označí kontakt Odhlášeno.

Ruční změny stavů, ruční přiřazení a mazání rezervací v nakonfigurované Codex
aplikaci používají stejný zámek. Přímé ruční zásahy do tabulky a původní aplikace
Claude tento zámek nepoužívají: neupravovat souběžně přiřazení/řádky jinými cestami.
Změny stavu přímo v tabulce nebo v původní aplikaci nerozesílají nabídky.

Resend deduplikuje podle klíče 24 hodin. Stejný obsah a klíč se opakují pouze
v bezpečném okně 23 hodin; pak se nejisté odeslání označí Nutná kontrola.
Stav Odesláno znamená přijetí Resendem, nikoli potvrzené doručení do schránky.
Chyba 4xx kromě limitu 429 vyžaduje kontrolu konfigurace v listu E-maily úklidu.
Limit 429 / dočasná chyba se zkusí při dalším spuštění, bez vytváření nové nabídky.
Odebrání kontaktu za nesplnění standardu je rozhodnutí majitele po kontrole;
není automatické. Znovupřihlášení se zatím provádí vědomou změnou E-mailing na
Přihlášeno v tabulce po žádosti kontaktu.

## Ověření před aktivací
Python: python -m unittest discover -s tests -v
Koordinátor: node tests/test_cleaning_gateway.cjs
Nejdřív otestovat nasazený koordinátor na kopii tabulky a vlastní testovací
adrese. Ověřit přijetí zprávy, potvrzení, druhý tým, odhlášení a neodeslání po něm.
Nesmí se testovat změnou skutečných rezervací nebo rozesílkou skutečným týmům.
Lokální testy nyní prošly; živá rozesílka a produkční setup zatím nejsou provedené.
