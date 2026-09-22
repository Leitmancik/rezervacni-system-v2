# Chalupa · Rezervační systém v2

Česká aplikace pro rezervace chalupy ve Vernířovicích. Nová samostatná verze
vycházející z [Chalupa_Codex](https://github.com/Leitmancik/Chalupa_Codex),
stav zdrojů `2966020`. Přehled úprav je v [DESIGN_CHANGES.md](DESIGN_CHANGES.md).

## Spuštění

Python 3.12:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python demo.py
CHALUPA_DEMO=1 streamlit run streamlit_app.py
```

Demo používá pouze místní SQLite ve `work/`. Ukázková data se vytvoří explicitně
příkazem `python demo.py`; do GitHubu se neukládají. `CHALUPA_DB` umožňuje jinou
cestu k databázi. Pro běh s Google Sheets vynechte `CHALUPA_DEMO` a nastavte
`.streamlit/secrets.toml` podle příkladu. SQLite na Streamlit Cloudu není trvalá.

## Funkce

- Výběr příjezdu a odjezdu, půldny při výměně hostů, aktuální dostupnost.
- Cena za celý pobyt s rozpisem nocí; kontaktní údaje až po volbě termínu.
- Správa rezervací, hledání, více stavových filtrů, CSV a Excel export.
- Stavy: Čeká na potvrzení, Potvrzeno - čeká na zaplacení, Zaplaceno.
- Základní a sezónní ceny; uložené ceny existujících rezervací se nemění.
- Úklidový tým a ruční přiřazení úklidu ke dni odjezdu.
- Volitelný koordinátor nabídek úklidu: [integrations/README.md](integrations/README.md).

## Fakturace

Formulář obsahuje fakturační adresu a volbu firmy s IČO/DIČ. Volitelná integrace
Fakturoidu vystaví a odešle zálohovku po schválení a vyúčtování po odjezdu
a úplném uhrazení zálohy (proces pro neplátce DPH). Aktivace a omezení:
[integrations/FAKTUROID.md](integrations/FAKTUROID.md).

## Data a konfigurace

Zachována kompatibilita původních listů a sloupců Google Sheets:

- `Rezervace`: Jméno | Příjmení | email | Datum - Start | Datum - Konec |
  Stav | ID | Vytvořeno | Cena celkem
- `Cenotvorba`: Od | Do | Cena za noc | Popis | ID
- `Úklid`: Jméno | E-mail

Další sloupce se hledají podle jména, existující sloupce se neposouvají.
Pouhé čtení data nemigruje. Před odesláním žádosti se znovu ověří cena i
obsazenost. Všechny tři stavy blokují termín, navazující pobyty jsou povolené.
Příjezd od 15:00, odjezd do 11:00, časové pásmo Europe/Prague.
Při překryvu cen platí kratší období; při shodě rozhoduje pořadí řádků.
Poslední den období zahrnuje noc začínající tímto dnem.

Tajné klíče, databáze, osobní data hostů a `.streamlit/secrets.toml` nepatří do
repozitáře. Historické konverzace nejsou součástí této verze.

## Ověření

```sh
python -m unittest discover -s tests -v
node tests/test_cleaning_gateway.cjs
```

Testy používají izolovanou místní databázi. CI provádí obě sady při pushi a PR.

## Nasazení

Ve Streamlit Community Cloud vyberte repozitář `Leitmancik/rezervacni-system-v2`,
větev `main`, soubor `streamlit_app.py` a Python 3.12. Produkční přihlašovací
údaje patří výhradně do zabezpečených Secrets. Nový repozitář sám o sobě
neaktualizuje původní nasazenou aplikaci.

### Aktuální omezení

Jde o vývojovou verzi. Správa je bez nastavení `admin.password` a bez zapnuté fakturace přístupná bez přihlášení.
Při zapnuté fakturaci se vyžaduje heslo majitele v Secrets.
Před zpřístupněním aplikace se skutečnými rezervacemi je potřeba oddělit oprávnění
hosta a majitele. Veřejnost zdrojového kódu neznamená připravenost správy pro hosty.
Google Sheets neposkytují atomickou kontrolu volného termínu a zápis mezi více
aplikacemi; společný transakční koordinátor rezervací zůstává dalším krokem.
Úklidové e-maily jsou vypnuté, dokud není samostatně nastavena integrace.
