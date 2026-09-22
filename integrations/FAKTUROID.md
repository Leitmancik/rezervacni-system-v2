# Zálohová fakturace rezervací – Fakturoid

Implementovaný proces pro českého **neplátce DPH**:

1. Host vyplní kontaktní údaje a fakturační adresu. Volitelně firmu, IČO a DIČ.
2. Majitel změní stav na „Potvrzeno - čeká na zaplacení“.
3. Koordinátor uloží jednu úlohu se snímkem ceny, termínu a odběratele. Přidělí
   číslo rezervace / VS z vyhrazené řady 9000000001–9999999999.
4. Minutový trigger založí odběratele a **zálohovou fakturu na 100 % ceny**.
   QR platba vychází z účtu a VS. Odeslání e-mailu zadá Fakturoidu.
5. V den odjezdu po 11:00 Europe/Prague vytvoří vyúčtovací fakturu navázanou na
   zálohovku (`related_id`). Podmínkou je úplně uhrazená záloha ve Fakturoidu.
   Při nedoplatku vyúčtování čeká a stav je vidět ve správě.
6. Vyúčtování odešle až po ověření odečtené zálohy (zbývá zaplatit nula).

Nasazeno a aktivováno 22. 9. 2026 v `chalupa-v2.streamlit.app` a ve verzi 3
stávajícího Google koordinátoru. Ověřeno živé připojení k Fakturoid API,
neplátce DPH, bankovní účet, přihlášení majitele, formulář a načtení fronty.
Trigger `processInvoices` běží vedle původního `processQueue`.
Lokální testy používají simulované API a izolované databáze. Celý cyklus se
skutečným vystavením a doručením faktury zatím nebyl v produkci ověřen.
Bankovní párování probíhá ve Fakturoidu. `processPayments` každou minutu
kontroluje až deset dosud nepřevzatých úhrad (nejdéle nekontrolované první).
Potvrzenou rezervaci označí jako zaplacenou až po ověření stavu `paid`, ID,
VS, částky, měny a shody termínu rezervace. Zapíše audit a připraví úklidové
e-maily stejnou frontou jako ruční změna stavu. Opakovaná kontrola je neduplikuje.

## Fakturoid

- Nastavit firmu jako neplátce DPH, CZK, správný účet Air Bank, QR platbu,
  splatnost a vzhled dokladu. PDF přílohu e-mailu nastavit podle preference
  ve Fakturoidu; text e-mailu vždy obsahuje odkaz na webfakturu s QR.
- Nastavit bankovní notifikace Air Bank pro párování plateb ve Fakturoidu.
- V Nastavení → Uživatelský účet → API přístupy vytvořit přístup typu
  **Client credentials**. Client ID a Client Secret patří pouze do Script
  Properties, nikdy do repozitáře, tabulky, formulářů hostů ani chatu.
- Slug je název účtu používaný v URL Fakturoid API.
- Zjistit ID bankovního účtu ve Fakturoid API (`GET bank_accounts.json`),
  případně z adresy editace bankovního účtu. Nejde o číslo účtu ani kód banky.
- Vyhradit číselnou řadu VS 9000000001–9999999999 pouze této integraci.
  Číslo daňového dokladu si dál přiděluje Fakturoid podle vlastní číselné řady.
- U zálohovek integrace výslovně nastaví návaznost `final_invoice` (faktura
  s úpravou), aby se běžná faktura **nevystavila hned po zaplacení**.
- Neměnit automaticky návaznost těchto zálohovek ve Fakturoidu. Vypnout
  automatické odeslání faktury vytvořené ze zálohy, pokud by zdvojovalo naši
  rozesílku. Automatické poděkování za přijetí platby je samostatné nastavení.

Dokumentace API:
- https://www.fakturoid.cz/api/v3/authorization
- https://www.fakturoid.cz/api/v3/invoices
- https://www.fakturoid.cz/api/v3/invoice-messages

## Google Apps Script

Použít **stejný projekt a nasazení** jako pro `integrations/cleaning.gs`,
aby všechny změny stavů a fakturace sdílely jeden `ScriptLock`.
Pokud úklid ještě není nasazený, vytvořit nový projekt s oběma soubory;
`setupBilling()` nepotřebuje Resend ani aktivní úklid.

1. Aktualizovat `cleaning.gs` a přidat nový soubor `billing.gs`.
2. Povolit pokročilou službu Google Sheets API (`Sheets`, v4).
3. Do **Project Settings → Script Properties** vložit:

| Klíč | Hodnota |
| --- | --- |
| `SHEET_ID` | ID používané Google tabulky |
| `API_SECRET` | Náhodný klíč alespoň 32 znaků, shodný s nastavením Streamlitu |
| `FAKTUROID_SLUG` | Název účtu ve Fakturoidu |
| `FAKTUROID_CLIENT_ID` | Client ID |
| `FAKTUROID_CLIENT_SECRET` | Client Secret |
| `FAKTUROID_USER_AGENT` | Např. `ChalupaReservations (kontakt@vasedomena.cz)` |
| `FAKTUROID_BANK_ACCOUNT_ID` | ID účtu Air Bank ve Fakturoidu |
| `FAKTUROID_NON_VAT_PAYER` | `true` – podle potvrzení majitele |
| `FAKTUROID_ENABLED` | Zpočátku `false`, po ověření `true` |

4. Spustit `setupBilling()` a autorizovat Google Sheets a vnější HTTP volání.
   Založí list **Faktury rezervací**, sloupec **Fakturační údaje**, audit a
   minutový trigger `processInvoices`. Nezakládá historické faktury.
5. Nasadit novou verzi webové aplikace vykonávanou pod vlastníkem projektu,
   přístupnou ze Streamlit serveru bez interaktivního Google přihlášení.
   Všechny požadavky autorizuje `API_SECRET`. Po změně kódu nestačí uložit editor:
   aktualizovat verzi existujícího nasazení.
6. Na kopii tabulky a testovacím Fakturoid účtu ověřit celý cyklus včetně
   vlastního testovacího e-mailu. Teprve potom aktivovat produkční nastavení.

List Faktury rezervací a vlastnost `BILLING_LAST_VS` **nemazat ani neresetovat**.
Jsou trvalou ochranou proti duplicitám i po smazání rezervace. Číselná řada
připouští mezery při nedokončeném zápisu. Původní interní UUID rezervací zůstávají
zachovaná; číselné označení / VS vzniká při prvním schválení s fakturací.

## Streamlit Cloud → Settings → Secrets

Doplnit níže uvedené sekce k existujícím údajům; nepřepisovat Google credentials:

```toml
[fakturoid]
enabled = true
url = "https://script.google.com/macros/s/DEPLOYMENT_ID/exec"
secret = "STEJNY_API_SECRET_JAKO_V_APPS_SCRIPT"

[admin]
password = "SILNE_UNIKATNI_HESLO_ALESPON_16_ZNAKU"
```

Při zapojeném úklidu musí mít `[cleaning_mail]` stejnou URL a secret.
Fakturoid Client Secret do Streamlitu nepotřebujeme: API volá pouze koordinátor.
Správa rezervací, cen, úklidu a správců je s fakturací dostupná až po přihlášení.
Veřejný formulář zůstává bez přihlášení. Existující heslo změnou v Secrets
zneplatní dřívější přihlášení. Nastavení hesla lze zapnout i bez fakturace.

Aplikaci nasadit z tohoto repozitáře do Streamlit Cloud po dokončení konfigurace.

## Obsluha a omezení

- Fakturační údaje starších rezervací lze doplnit ve správě v sekci Fakturace.
  Schválení s aktivní fakturací bez adresy či kladné uložené ceny je odmítnuto.
- Předchozí potvrzené rezervace se nefakturují zpětně; konkrétní rezervaci lze
  vědomě zařadit tlačítkem „Vytvořit fakturu ke schválené rezervaci“.
- Opakované schválení používá stejnou úlohu. Zachová se uložená cena a termín.
- Změna termínu/ceny, zrušení či smazání rezervace vyžaduje kontrolu již
  vystavených dokladů ve Fakturoidu. Smazání rezervace není storno faktury.
- Při timeoutu před založením dokladu se trvale uloží stav „Vystavování“.
  Následující pokus pouze dohledá doklad přes `custom_id`; pokud není dohledán,
  nový POST se neprovede. Totéž platí pro kontakt a odeslání e-mailu.
- U nejasného odeslání se kontroluje `sent_at`. „Odesláno“ znamená přijetí
  požadavku Fakturoidem, nikoli prokázané doručení zákazníkovi.
- „Znovu ověřit / pokračovat“ neopakuje nejisté zápisy naslepo. U definitivní
  chyby 4xx lze opravit konfiguraci a pokračovat. Nejasný zápis bez nalezeného
  výsledku musí prověřit obsluha; frontu kvůli tomu nemažte.
- Worker vyřídí maximálně tři úlohy v běhu; chyby mají prodlevu až jednu hodinu.
  Zkontrolovat limit API požadavků tarifu i kvóty Apps Script podle počtu pobytů.
- Přenos úhrad používá pravidelné dotazování API, nepotřebuje webhook ani
  bankovní e-mail do rezervační aplikace. Při změně ceny, termínu, zrušení či
  smazání rezervace se stav nepřepíše; chyba je vidět ve fakturační správě.
  Vrácení platby nebo ruční odebrání úhrady ve Fakturoidu automaticky neruší
  již převzatý stav zaplaceno. Doklady vytvořené mimo tuto integraci se nepárují.

## Testy

```sh
python -m unittest discover -s tests -v
node tests/test_cleaning_gateway.cjs
node tests/test_billing_gateway.cjs
```

Mock API ověřuje schválení, opakované schválení, cenu a VS, osobu i firmu,
chybějící adresu/cenu, ztracené odpovědi při založení kontaktu/faktury/odeslání,
429/422, zrušené/smazané/změněné rezervace, čas odjezdu, úplné uhrazení zálohy,
jediné vyúčtování i zotavení po nejistém vystavení vyúčtování.
Živý test API a produkční nasazení je nutné provést po doplnění přístupů.
