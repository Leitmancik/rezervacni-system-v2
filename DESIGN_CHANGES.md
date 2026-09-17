# Změny UX/UI · 17. 9. 2026

Výchozí projekt: Chalupa_Codex, commit 2966020. Nový repozitář a samostatný
pracovní adresář; původní nasazení se touto verzí nemění.

## Provedené změny

| Oblast | Změna | Důvod |
| --- | --- | --- |
| Úvod | Světlá šalvějová plocha, serifový nadpis a vlastní CSS ilustrace chalupy | Klidný, osobnější charakter bez závislosti na externí fotografii |
| Text úvodu | „Na chvíli vypnout. A být spolu.“ | Krátký, srozumitelný úvod s konkrétním postupem rezervace |
| Navigace | Váš pobyt / Rezervace / Ceník / Úklid | Kratší názvy vhodné i pro malé displeje |
| Formulář | 01 Termín a cena → 02 Kontaktní údaje | Host nejdříve ověří termín a cenu, teprve pak vyplňuje údaje |
| Dostupnost | Zpráva „Termín je volný“ a jasná celková cena | Menší nejistota před odesláním |
| Akce | „Odeslat žádost o rezervaci“ | Odlišuje žádost od definitivního potvrzení |
| Text po akci | Informace o potvrzení na stránce a neodesílání e-mailu | Neslibuje automatické potvrzení, které systém neposílá |
| Mobil a tablet | Jeden viditelný měsíc do šířky 1100 px, další dostupné šipkami | Formulář není až pod dvěma kalendáři; sedm dnů se vejde na řádek |
| Ovládání | Dny vysoké 44 px, pole se 16px písmem, viditelný focus | Snazší ovládání dotykem i klávesnicí |
| Výběr pobytu | Tmavé krajní dny, zelený pás mezi nimi | Zřetelné rozlišení vybraného pobytu od obsazenosti |
| Správa | Stručné nadpisy a kompaktní souhrny na telefonu | Důležité údaje dostupné rychleji |
| Úklid | Srozumitelná zpráva o neaktivní rozesílce s odkazem na ruční postup | Provozní informace místo názvu dodavatele e-mailové služby |

## Konfigurace veřejného projektu

Konkrétní kontaktní adresy integrace jsou nahrazené Script Properties
`MAIL_FROM` a `MAIL_REPLY_TO`. Při aktivaci je nutné doplnit obě hodnoty.
Dokumentace obsahuje obecné příklady místo identifikátoru produkční tabulky
a adresy původního nasazení.

## Zachovaná pravidla

Stavy rezervací, barvy obsazenosti, půldny, cenová období, cenové snapshoty,
exporty, úklid a datové schéma zůstávají kompatibilní s původním projektem.
Integrace e-mailů je převzatá a nadále ve výchozím stavu vypnutá.

## Další doporučené kroky

- Přihlášení majitele a oddělení správy před veřejným ostrým provozem.
- Jednotné transakční ukládání rezervací pro všechny aplikace nad stejnými daty.
- Skutečné fotografie, kapacita a vybavení chalupy po dodání ověřených podkladů.
- Aktivace úklidových e-mailů po ověření na kopii tabulky.
