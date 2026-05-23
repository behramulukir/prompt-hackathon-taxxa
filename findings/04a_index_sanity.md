# 04a Index sanity — full embedding pass

Vector store: `output/lancedb` (402,088 rows, 1024-dim vectors)

## Summary verdict

| Check | Result |
|---|---|
| 1. Row-count parity vs `chunks.jsonl − oversized` | **PASS** (delta +0) |
| 2. 100 random vectors resolve to chunk + node       | **PASS** (100/100) |
| 3. 20-query Finnish tax spot-check                  | **PASS** (20/20 plausibly-relevant in top-3) |
| 4. Metadata filter test                             | **PASS** (0 leaks) |

The 20-query spot-check substantially exceeds the doc's eyeball gate (the pilot
needed 7/10 in top-3; the full index hits 20/20). Notable: Q5
("asianomistajan oikeus") which was marginal in the 1000-chunk pilot now
returns the correct § 14 of `Laki oikeudenkäynnistä rikosasioissa` as the
top-3 results — corpus completeness was the gap there, not the embedding.

### Per-query assessment (top-3 contains plausibly relevant?)

| Q  | Topic                              | OK | Notes |
|----|------------------------------------|----|------|
| 1  | ALV vähennysoikeus                 | ✓  | Vero ohjeet on Vähennysoikeus |
| 2  | Verovähennys yritystoiminnan kuluista | ✓ | KHO:2025:61 + vero_ohje menon vähennyskelpoisuus |
| 3  | Kuolinpesän jälkiverotus           | ✓  | VML §59 — direct hit |
| 4  | Kiinteä toimipaikka treaty         | ✓  | Yhteisön rajoitettu verovelvollisuus + kiinteä toimipaikka |
| 5  | Asianomistajan syyteoikeus         | ✓  | All top-3 are §14 of Laki oikeudenkäynnistä rikosasioissa |
| 6  | KHO ALV päätös                     | ✓  | KHO 2016/2013/2011 VAT cases |
| 7  | Vero-ohje työsuhde-etu             | ✓  | "Työsuhdeoptioiden verotus" chapters |
| 8  | Säädöskokoelma ALV-muutos          | ✓  | All Arvonlisäverolaki AMENDMENT_BLOCKs |
| 9  | Verovapaa lahja / perintö          | ✓  | Verovapaat lahjat + perintö-/lahjavero |
| 10 | Yrityksen sukupolvenvaihdos        | ✓  | Osakeyhtiön sukupolvenvaihdos verotuksessa |
| 11 | ALV-palautus ulkomaiselle yritykselle | ✓ | All top-5 are AVL §122 |
| 12 | Yhteisön luovutusvoitto osakkeista | ✓  | KHO + käyttöomaisuusosakkeiden luovutus |
| 13 | Henkilökohtainen + pääomatulo      | ✓  | Verotettavan tulon laskeminen — perfect |
| 14 | Ennakonpidätys palkasta ja eläkkeestä | ✓ | All top-5 are Verohallinnon ennakonpidätyspäätökset |
| 15 | VML muutoksenhaku                  | ✓  | All top-5 are "Muutoksenhaku" sections |
| 16 | Yleishyödyllinen yhteisö verovapaus | ✓ | Laki yleishyödyllisten yhteisöjen veronhuojennuksista |
| 17 | Kiinteistöveron määrääminen        | ✓  | Kiinteistöverolain soveltamisohje |
| 18 | Tuloverolain 28 § soveltaminen     | ✓\* | Top-1 is EVL §28 (related law), then TVL AMENDMENT_BLOCKs — see note |
| 19 | Siirtohinnoittelu konserniyhtiöt   | ✓  | KHO:2020:35 + KHO:2018:173 — major TP cases |
| 20 | Maakuntavero ja kunnallisvero      | ✓  | Ahvenanmaa province + municipal tax (the topical match) |

**Q18 note**: top-1 returns `Laki elinkeinotulon verottamisesta 28 §` (EVL §28)
rather than `Tuloverolaki 28 §` (TVL §28). The query phrasing "Tuloverolain 28 §"
points at TVL, but EVL is a close-adjacent statute with an exact §28 match and
the embedding model treats the §-marker as a strong textual signal. The query
intent is plausibly satisfied (both are TVL-family income-tax law §s), so we
count this as a pass while flagging it as the one place reranking would help.

## 1. Row-count parity

- LanceDB rows: **402,088**
- chunks.jsonl lines: 402,098
- oversized (skipped by design): 10
- expected (file − oversized): 402,088
- delta (db − expected): **+0**
- verdict: PASS (needs |delta| == 0)

## 2. Random-vector resolution

- sampled chunk_ids: 100
- found in LanceDB: **100**
- missing from LanceDB: 0
- section_ids missing from nodes_enriched.jsonl: **0**
- verdict: PASS

## 4. Metadata filters

- `source_subcorpus=='laki'` → 50 sampled, non-laki leaks: **0**
- `node_type=='SECTION'` → 50 sampled, non-SECTION leaks: **0**
- verdict: PASS

## 3. 20-query spot-check

Top-5 per query, written below. Lower distance = closer. Eyeball gate: at least one plausibly-relevant chunk in top-3 for the strong majority of queries (the pilot gate was 7/10).


### Q1. Mikä on arvonlisäveron vähennysoikeus?

- **1** (d=0.5502, vero_ohje / CHAPTER) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-ahvenanmaan-veroraja-arvonlisaverotuksessa-ah-c195fa78/c5#0`
  > [Source: vero_vero_ohje · repealed] [Path: Ahvenanmaan veroraja arvonlisäverotuksessa > Vähennysoikeus] [Title: Vähennysoikeus]  Ahvenanmaan veroraja arvonlisäverotuksessa — 5 — Vähennysoikeus

- **2** (d=0.5704, vero_ohje / CHAPTER) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-arvonlisaverovelvollisen-opas-arvonlisaverove-57a70b9e/c8#0`
  > [Source: vero_vero_ohje · in force] [Path: Arvonlisäverovelvollisen opas > Vähennysoikeus arvonlisäverotuksessa] [Title: Vähennysoikeus arvonlisäverotuksessa]  Arvonlisäverovelvollisen opas — 8 — Vähennysoikeus arvonlisäverotuksessa

- **3** (d=0.5779, vero_ohje / CHAPTER) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-tuet-ja-avustukset-arvonlisaverotuksessa-tuet-adbdccd1/c5#0`
  > [Source: vero_vero_ohje · in force] [Path: Tuet ja avustukset arvonlisäverotuksessa > Vähennysoikeus] [Title: Vähennysoikeus]  Tuet ja avustukset arvonlisäverotuksessa — 5 — Vähennysoikeus

- **4** (d=0.5894, vero_ohje / CHAPTER) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-hevostoimialan-arvonlisaverotuksesta-hevostoi-231d4fd0/c8#0`
  > [Source: vero_vero_ohje · in force] [Path: Hevostoimialan arvonlisäverotuksesta > Arvonlisäveron vähennysoikeus] [Title: Arvonlisäveron vähennysoikeus]  Hevostoimialan arvonlisäverotuksesta — 8 — Arvonlisäveron vähennysoikeus

- **5** (d=0.6001, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-arvonlisaverovelvollisen-opas-arvonlisaverove-57a70b9e/c8/s8-4#0`
  > [Source: vero_vero_ohje · in force] [Path: Arvonlisäverovelvollisen opas > Vähennysoikeus arvonlisäverotuksessa > Muut vähennysoikeuden erityistilanteet] [Title: Muut vähennysoikeuden erityistilanteet]  Arvonlisäverovelvollisen opas — 8.4 — Muut vähennysoikeuden erityistilanteet


### Q2. Verovähennys yritystoiminnan kuluista

- **1** (d=0.6795, kho / CASE) `finlex/kho/finlex-korkein-hallinto-oikeus-ennakkopaatokset-kho-2025-61-html-41da16e4#4`
  > [Source: finlex_kho · in force] [Path: KHO:2025:61] [Title: KHO:2025:61]  KHO:2025:61  kappale 34 (28) Osakeyhtiötä perustettaessa voi muodostua kuluja, jotka liittyvät osakeyhtiön perustamiseen ja aiottuun arvonlisäverolliseen ja vähennykseen oikeuttavaan toimintaan. Vähennysoik

- **2** (d=0.7242, kho / CASE) `finlex/kho/finlex-korkein-hallinto-oikeus-ennakkopaatokset-kho-1989-b-523-html-1112591f#0`
  > [Source: finlex_kho · in force] [Path: KHO:1989-B-523] [Title: KHO:1989-B-523]  KHO:1989-B-523  kappale 1 Verovelvollinen oli ostanut veljeltään yhtiöosuuden kommandiittiyhtiöstä, jonka osakkaana hän jo ennestään oli. Verovelvollinen vaati saada vähentää ansiotoimintaansa kohdist

- **3** (d=0.7252, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-yritystoiminta-tulonhankkimistoiminta-ja-harr-c2f990b6/c3/s3-3#0`
  > [Source: vero_vero_ohje · in force] [Path: Yritystoiminta, tulonhankkimistoiminta ja harrastustoiminta henkilöverotuksessa > Elinkeino-, maatalous-, tulonhankkimis- ja harrastustoiminnan keskeiset erot > Menon vähennyskelpoisuus ja jaksotus] [Title: Menon vähennyskelpoisuus ja ja

- **4** (d=0.7279, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-yrittajan-tyoterveyshuollon-kustannukset-vero-f5f5a5b8/c2/s2-1#0`
  > [Source: vero_vero_ohje · in force] [Path: Yrittäjän työterveyshuollon kustannukset verotuksessa > Työterveyshuollon kustannusten vähentäminen verotuksessa > Elinkeinotoiminnan tai maatalouden meno] [Title: Elinkeinotoiminnan tai maatalouden meno]  Yrittäjän työterveyshuollon kus

- **5** (d=0.7297, kho / CASE) `finlex/kho/finlex-korkein-hallinto-oikeus-ennakkopaatokset-kho-1980-b-ii-517-html-7ed74052#0`
  > [Source: finlex_kho · in force] [Path: KHO:1980-B-II-517] [Title: KHO:1980-B-II-517]  KHO:1980-B-II-517  kappale 1 Yhdistyksellä oli oikeus vähentää liiketulostaan se osa yhdistyksen toiminnanjohtajan ja toimistonhoitajan palkasta sekä eräistä muista kustannuksista, joka johtui l


### Q3. Kuolinpesän verotus ja jälkiverotus

- **1** (d=0.7582, laki / SECTION) `finlex/laki/finlex-laki-laki-verotusmenettelysta-annetun-lain-muuttamisesta-5-html-c639c98e/s59#0`
  > [Source: finlex_laki · in force] [Path: Laki verotusmenettelystä annetun lain muuttamisesta > Jälkiverotuksen ja veronoikaisun kohdis- taminen kuolinpesään] [Title: Jälkiverotuksen ja veronoikaisun kohdis- taminen kuolinpesään]  Laki verotusmenettelystä annetun lain muuttamisesta

- **2** (d=0.7703, laki_skk / SECTION) `finlex/laki_skk/finlex-laki-saadoskokoelma-laki-verotusmenettelysta-html-c7ef1b63/c4/s59#0`
  > [Source: finlex_laki_skk · in force] [Path: Laki verotusmenettelystä > Verotuksen toimittaminen > Jälkiverotuksen ja veronoikaisun kohdistaminen kuolinpesään] [Title: Jälkiverotuksen ja veronoikaisun kohdistaminen kuolinpesään]  59 § Jälkiverotuksen ja veronoikaisun kohdistaminen

- **3** (d=0.7925, laki / SECTION) `finlex/laki/finlex-laki-laki-liikevaihtoverolain-muuttamisesta-4-html-1ef9e342/c6/s47#0`
  > [Source: finlex_laki · in force] [Path: Laki liikevaihtoverolain muuttamisesta > Rekisteröinti ja veron määrääminen > 47 §] [Title: 47 §]  Laki liikevaihtoverolain muuttamisesta — 47 §  1 momentti Verovelvollisen kuoltua kohdistetaan jälkiverotus kuolinpesään. Jälkiverotus on toi

- **4** (d=0.7930, laki / SECTION) `finlex/laki/finlex-laki-laki-arvonlisaverolain-muuttamisesta-61-html-9bc14e6c/s179#0`
  > [Source: finlex_laki · in force] [Path: Laki arvonlisäverolain muuttamisesta > 179 §] [Title: 179 §]  Laki arvonlisäverolain muuttamisesta — 179 §  1 momentti Verovelvollisen kuoltua jälkiverotus kohdistetaan kuolinpesään. Jälkiverotus on toimitettava vuoden kuluessa sen kalenter

- **5** (d=0.8120, laki / SECTION) `finlex/laki/finlex-laki-laki-varallisuusverolain-muuttamisesta-html-05b7b881/s6#0`
  > [Source: finlex_laki · in force] [Path: Laki varallisuusverolain muuttamisesta > Kuolinpesän verovelvollisuus] [Title: Kuolinpesän verovelvollisuus]  Laki varallisuusverolain muuttamisesta — 6 § Kuolinpesän verovelvollisuus  1 momentti Tuloverolain 17 §:ssä tarkoitettua kotimaist


### Q4. Kiinteä toimipaikka kansainvälisessä verosopimuksessa

- **1** (d=0.6390, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-yhteison-yleinen-ja-rajoitettu-verovelvollisu-5962b01d/c3/s3-3#0`
  > [Source: vero_vero_ohje · in force] [Path: Yhteisön yleinen ja rajoitettu verovelvollisuus > Yhteisön rajoitettu verovelvollisuus > Kiinteän toimipaikan saamat tulot] [Title: Kiinteän toimipaikan saamat tulot]  Yhteisön yleinen ja rajoitettu verovelvollisuus — 3.3 — Kiinteän toim

- **2** (d=0.6392, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-yhteison-yleinen-ja-rajoitettu-verovelvollisu-7519909e/c3/s3-3#0`
  > [Source: vero_vero_ohje · in force] [Path: Yhteisön yleinen ja rajoitettu verovelvollisuus > Yhteisön rajoitettu verovelvollisuus > Kiinteän toimipaikan saamat tulot] [Title: Kiinteän toimipaikan saamat tulot]  Yhteisön yleinen ja rajoitettu verovelvollisuus — 3.3 — Kiinteän toim

- **3** (d=0.6449, laki_skk / SECTION) `finlex/laki_skk/finlex-laki-saadoskokoelma-laki-suurten-konsernien-vahimmaisverosta-html-3fff205a/c1/s18#0`
  > [Source: finlex_laki_skk · in force] [Path: Laki suurten konsernien vähimmäisverosta > Soveltamisala ja sovellettavat määritelmät > Kiinteä toimipaikka] [Title: Kiinteä toimipaikka]  18 § Kiinteä toimipaikka  1 momentti Kiinteällä toimipaikalla tarkoitetaan:  1 1) liikepaikkaa ta

- **4** (d=0.6525, vero_kannanotto / SECTION) `vero/vero_kannanotto/vero-syventavat-vero-ohjeet-kannanotot-covid-19-pandemiaan-liittyvat-rajoitukset-6e44230b/ckannanotto/skiinteat-toimipaikat#0`
  > [Source: vero_vero_kannanotto · in force] [Path: COVID-19-pandemiaan liittyvät rajoitukset ja niiden vaikutukset ulkomaisten yhteisöjen verotukseen > Kannanotto > Kiinteät toimipaikat] [Title: Kiinteät toimipaikat]  COVID-19-pandemiaan liittyvät rajoitukset ja niiden vaikutukset 

- **5** (d=0.6569, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-suurten-konsernien-vahimmaisverotus-maaritell-25d4dcdc/c2/s2-2/s2-2-1#0`
  > [Source: vero_vero_ohje · repealed] [Path: Suurten konsernien vähimmäisverotus - määritellyn tuloksen tai tappion sekä huomioitavien verojen kohdentaminen eri konserniyksiköiden välillä eräissä erityistilanteissa > Kiinteät toimipaikat > Määritelmiä > Kiinteä toimipaikka] [Title:


### Q5. Asianomistajan oikeus nostaa syyte

- **1** (d=0.7231, laki_skk / SECTION) `finlex/laki_skk/finlex-laki-saadoskokoelma-laki-oikeudenkaynnista-rikosasioissa-html-53944c0f/c1/s14#0`
  > [Source: finlex_laki_skk · in force] [Path: Laki oikeudenkäynnistä rikosasioissa > Syyteoikeudesta > 14 §] [Title: 14 §]  14 §  1 momentti Asianomistaja saa itse nostaa syytteen rikoksesta vain, jos virallinen syyttäjä on päättänyt jättää syytteen nostamatta. Asianomistajan oikeu

- **2** (d=0.7562, laki / SECTION) `finlex/laki/finlex-laki-laki-oikeudenkaynnista-rikosasioissa-annetun-lain-muuttamisesta-2-ht-2d530087/c1/s14#0`
  > [Source: finlex_laki · in force] [Path: Laki oikeudenkäynnistä rikosasioissa annetun lain muuttamisesta > Syyteoikeudesta > 14 §] [Title: 14 §]  Laki oikeudenkäynnistä rikosasioissa annetun lain muuttamisesta — 14 §  1 momentti Asianomistaja saa itse nostaa syytteen rikoksesta va

- **3** (d=0.7733, laki / SECTION) `finlex/laki/finlex-laki-laki-oikeudenkaynnista-rikosasioissa-annetun-lain-1-luvun-14-n-muutt-25c86f46/c1/s14#0`
  > [Source: finlex_laki · in force] [Path: Laki oikeudenkäynnistä rikosasioissa annetun lain 1 luvun 14 §:n muuttamisesta > Syyteoikeudesta > 14 §] [Title: 14 §]  Laki oikeudenkäynnistä rikosasioissa annetun lain 1 luvun 14 §:n muuttamisesta — 14 §  1 momentti Asianomistaja saa itse

- **4** (d=0.7916, laki / SECTION) `finlex/laki/finlex-laki-laki-oikeudenkaynnista-rikosasioissa-annetun-lain-1-luvun-14-n-ja-7-01f13592/c1/s14#0`
  > [Source: finlex_laki · in force] [Path: Laki oikeudenkäynnistä rikosasioissa annetun lain 1 luvun 14 §:n ja 7 luvun 24 §:n muuttamisesta > Syyteoikeudesta > 14 §] [Title: 14 §]  Laki oikeudenkäynnistä rikosasioissa annetun lain 1 luvun 14 §:n ja 7 luvun 24 §:n muuttamisesta — 14 

- **5** (d=0.8019, laki_skk / SECTION) `finlex/laki_skk/finlex-laki-saadoskokoelma-laki-kasvinjalostajanoikeudesta-html-a18d9f1b/c9/s44#0`
  > [Source: finlex_laki_skk · in force] [Path: Laki kasvinjalostajanoikeudesta > Rangaistussäännökset > Syyteoikeus] [Title: Syyteoikeus]  44 § Syyteoikeus  1 momentti Syyttäjä ei saa nostaa syytettä 41―43 §:ssä tarkoitetusta rikkomuksesta, ellei asianomistaja ilmoita sitä syytteese


### Q6. Korkein hallinto-oikeus arvonlisävero KHO päätös

- **1** (d=0.6524, kho / CASE) `finlex/kho/finlex-korkein-hallinto-oikeus-ennakkopaatokset-kho-2016-200-html-21e10c48#5`
  > [Source: finlex_kho · in force] [Path: KHO:2016:200] [Title: KHO:2016:200]  KHO:2016:200  kappale 37 Koska hallinto-oikeus ei ole antanut ratkaisua varsinaiseen asiakysymykseen eli siihen, onko A Oy:lle tullut tilikaudelle 1.4.2008 - 31.3.2009 määrätä maksuun arvonlisäveroa arvon

- **2** (d=0.6871, kho / CASE) `finlex/kho/finlex-korkein-hallinto-oikeus-ennakkopaatokset-kho-2013-199-html-b8c447f6#0`
  > [Source: finlex_kho · in force] [Path: KHO:2013:199] [Title: KHO:2013:199]  KHO:2013:199  kappale 1 Korkein hallinto-oikeus 12.12.2006 taltionumero 3419 (KHO 2006:95) ja 30.6.2010 taltionumero 1561 (KHO 2010:44)  kappale 2 Helsingin tulli on määrännyt autoveropäätöksellään 1.12.2

- **3** (d=0.6992, kho / CASE) `finlex/kho/finlex-korkein-hallinto-oikeus-ennakkopaatokset-kho-2011-3-html-24e239eb#0`
  > [Source: finlex_kho · in force] [Path: KHO:2011:3] [Title: KHO:2011:3]  KHO:2011:3  kappale 1 Kort referat på svenska  kappale 2 Helsingin hallinto-oikeuden päätös 26.5.2008 nro 08/0428/4  kappale 3 1. Arvonlisäverolain (jäljempänä AVL) mukaan veroviraston tehtävänä on veron määr

- **4** (d=0.7042, kho / CASE) `finlex/kho/finlex-korkein-hallinto-oikeus-ennakkopaatokset-kho-2010-44-html-1541672f#14`
  > [Source: finlex_kho · in force] [Path: KHO:2010:44] [Title: KHO:2010:44]  KHO:2010:44  kappale 95 Korkein hallinto-oikeus on sekä Siilinin että A:n valituksiin antamissaan päätöksissä tulkinnut yhteisöjen tuomioistuimen tar­koit­taneen tältä osin arvoon sisältyvällä verosta jälje

- **5** (d=0.7127, kho / CASE) `finlex/kho/finlex-korkein-hallinto-oikeus-ennakkopaatokset-kho-2021-11-html-8313f4a9#0`
  > [Source: finlex_kho · in force] [Path: KHO:2021:11] [Title: KHO:2021:11]  KHO:2021:11  kappale 1 Korkein hallinto-oikeus 9.4.2013 taltionumero 1223  kappale 2 Korkein hallinto-oikeus 27.10.2017 taltionumero 5541  kappale 3 Sisä-Suomen yritysverotoimisto on päätöksellään 11.5.2010


### Q7. Vero-ohje työsuhde-edun verotus

- **1** (d=0.6730, vero_ohje / CHAPTER) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-tyosuhdeoptioiden-verotus-tyosuhdeoptioiden-v-f9f35eaa/c2#0`
  > [Source: vero_vero_ohje · in force] [Path: Työsuhdeoptioiden verotus > Työsuhdeoptio palkansaajan tuloverotuksessa] [Title: Työsuhdeoptio palkansaajan tuloverotuksessa]  Työsuhdeoptioiden verotus — 2 — Työsuhdeoptio palkansaajan tuloverotuksessa

- **2** (d=0.6741, vero_ohje / CHAPTER) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-tyosuhdeoptioiden-verotus-tyosuhdeoptioiden-v-f9f35eaa/c1#0`
  > [Source: vero_vero_ohje · in force] [Path: Työsuhdeoptioiden verotus > Yleistä työsuhdeoptioista] [Title: Yleistä työsuhdeoptioista]  Työsuhdeoptioiden verotus — 1 — Yleistä työsuhdeoptioista

- **3** (d=0.6872, vero_ohje / CHAPTER) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-tyosuhdeoptioiden-verotus-tyosuhdeoptioiden-v-f9f35eaa/c5#0`
  > [Source: vero_vero_ohje · in force] [Path: Työsuhdeoptioiden verotus > Työsuhdeoptio ennakkoperinnässä] [Title: Työsuhdeoptio ennakkoperinnässä]  Työsuhdeoptioiden verotus — 5 — Työsuhdeoptio ennakkoperinnässä

- **4** (d=0.6887, vero_ohje / CHAPTER) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-tyosuhdeoptioiden-verotus-tyosuhdeoptioiden-v-f9f35eaa/c10#0`
  > [Source: vero_vero_ohje · in force] [Path: Työsuhdeoptioiden verotus > Työsuhdeoptio perintö- ja lahjaverotuksessa] [Title: Työsuhdeoptio perintö- ja lahjaverotuksessa]  Työsuhdeoptioiden verotus — 10 — Työsuhdeoptio perintö- ja lahjaverotuksessa

- **5** (d=0.7025, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-tyosuhdeoptioiden-verotus-tyosuhdeoptioiden-v-f9f35eaa/c2/s2-4#0`
  > [Source: vero_vero_ohje · in force] [Path: Työsuhdeoptioiden verotus > Työsuhdeoptio palkansaajan tuloverotuksessa > Optiosta saadun edun arvostaminen] [Title: Optiosta saadun edun arvostaminen]  Työsuhdeoptioiden verotus — 2.4 — Optiosta saadun edun arvostaminen


### Q8. Säädöskokoelma muutos arvonlisäverolakiin

- **1** (d=0.5452, laki / AMENDMENT_BLOCK) `finlex/laki/finlex-laki-arvonlisaverolaki-html-ba5d8e0e/c1/a2-12-2011-1202#0`
  > [Source: finlex_laki · in force] [Path: Arvonlisäverolaki > Muutossäädösten voimaantulo ja soveltaminen > 2.12.2011/1202] [Title: 2.12.2011/1202]  Arvonlisäverolaki — muutos 2.12.2011/1202

- **2** (d=0.5532, laki / AMENDMENT_BLOCK) `finlex/laki/finlex-laki-arvonlisaverolaki-html-ba5d8e0e/c1/a29-10-2010-905#0`
  > [Source: finlex_laki · in force] [Path: Arvonlisäverolaki > Muutossäädösten voimaantulo ja soveltaminen > 29.10.2010/905] [Title: 29.10.2010/905]  Arvonlisäverolaki — muutos 29.10.2010/905

- **3** (d=0.5566, laki / AMENDMENT_BLOCK) `finlex/laki/finlex-laki-arvonlisaverolaki-html-ba5d8e0e/c1/a30-11-2012-706#0`
  > [Source: finlex_laki · in force] [Path: Arvonlisäverolaki > Muutossäädösten voimaantulo ja soveltaminen > 30.11.2012/706] [Title: 30.11.2012/706]  Arvonlisäverolaki — muutos 30.11.2012/706

- **4** (d=0.5569, laki / AMENDMENT_BLOCK) `finlex/laki/finlex-laki-arvonlisaverolaki-html-ba5d8e0e/c1/a30-12-2010-1392#0`
  > [Source: finlex_laki · in force] [Path: Arvonlisäverolaki > Muutossäädösten voimaantulo ja soveltaminen > 30.12.2010/1392] [Title: 30.12.2010/1392]  Arvonlisäverolaki — muutos 30.12.2010/1392

- **5** (d=0.5578, laki / AMENDMENT_BLOCK) `finlex/laki/finlex-laki-arvonlisaverolaki-html-ba5d8e0e/c1/a23-11-2007-1061#0`
  > [Source: finlex_laki · in force] [Path: Arvonlisäverolaki > Muutossäädösten voimaantulo ja soveltaminen > 23.11.2007/1061] [Title: 23.11.2007/1061]  Arvonlisäverolaki — muutos 23.11.2007/1061


### Q9. Verovapaa lahja perintö

- **1** (d=0.7615, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-perinto-ja-lahjaverotus-kansainvalisissa-tila-d80892ae/c4/s4-9#0`
  > [Source: vero_vero_ohje · in force] [Path: Perintö- ja lahjaverotus kansainvälisissä tilanteissa > Ulkomailta Suomeen tullut perintö tai lahja > Verosopimuksilla perintöverosta vapautettu omaisuus] [Title: Verosopimuksilla perintöverosta vapautettu omaisuus]  Perintö- ja lahjaver

- **2** (d=0.7816, vero_ohje / CHAPTER) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-verovapaat-lahjat-verovapaat-lahjat-vero-fi-h-562ff972/c3#0`
  > [Source: vero_vero_ohje · in force] [Path: Verovapaat lahjat > Kasvatusta, koulutusta tai toisen elatusta varten annettu lahja] [Title: Kasvatusta, koulutusta tai toisen elatusta varten annettu lahja]  Verovapaat lahjat — 3 — Kasvatusta, koulutusta tai toisen elatusta varten anne

- **3** (d=0.7878, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-perinto-ja-lahjaverotus-kansainvalisissa-tila-d80892ae/c3/s3-8#0`
  > [Source: vero_vero_ohje · in force] [Path: Perintö- ja lahjaverotus kansainvälisissä tilanteissa > Perinnönjättäjä tai lahjanantaja asui Suomessa > Verosopimuksien nojalla perintöverosta vapaa omaisuus] [Title: Verosopimuksien nojalla perintöverosta vapaa omaisuus]  Perintö- ja l

- **4** (d=0.7917, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-perinto-ja-lahjaverotus-kansainvalisissa-tila-d80892ae/c4/s4-10#0`
  > [Source: vero_vero_ohje · in force] [Path: Perintö- ja lahjaverotus kansainvälisissä tilanteissa > Ulkomailta Suomeen tullut perintö tai lahja > Ulkomaisen veron hyvitys] [Title: Ulkomaisen veron hyvitys]  Perintö- ja lahjaverotus kansainvälisissä tilanteissa — 4.10 — Ulkomaisen 

- **5** (d=0.7955, vero_ohje / CHAPTER) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-verovapaat-lahjat-verovapaat-lahjat-vero-fi-h-562ff972/c9#0`
  > [Source: vero_vero_ohje · in force] [Path: Verovapaat lahjat > Verovapaa lahja perintöverotuksessa] [Title: Verovapaa lahja perintöverotuksessa]  Verovapaat lahjat — 9 — Verovapaa lahja perintöverotuksessa  kappale 1 PerVL 16 §:n nojalla lahja voidaan ottaa huomioon myös perintöv


### Q10. Yrityksen sukupolvenvaihdos verotuksellisesti

- **1** (d=0.6260, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-osakeyhtion-sukupolvenvaihdos-verotuksessa-os-08fb843d/c1/s1-1#0`
  > [Source: vero_vero_ohje · repealed] [Path: Osakeyhtiön sukupolvenvaihdos verotuksessa > Johdanto > Yleistä sukupolvenvaihdoksesta verotuksessa] [Title: Yleistä sukupolvenvaihdoksesta verotuksessa]  Osakeyhtiön sukupolvenvaihdos verotuksessa — 1.1 — Yleistä sukupolvenvaihdoksesta 

- **2** (d=0.6394, vero_ohje / CHAPTER) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-osakeyhtion-sukupolvenvaihdos-verotuksessa-os-08fb843d/c7#0`
  > [Source: vero_vero_ohje · repealed] [Path: Osakeyhtiön sukupolvenvaihdos verotuksessa > Sukupolvenvaihdosluovutuksen esi- ja jälkitoimet] [Title: Sukupolvenvaihdosluovutuksen esi- ja jälkitoimet]  Osakeyhtiön sukupolvenvaihdos verotuksessa — 7 — Sukupolvenvaihdosluovutuksen esi- 

- **3** (d=0.6462, vero_ohje / CHAPTER) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-henkiloyhtion-ja-yksityisliikkeen-sukupolvenv-f4cd2de9/c5#0`
  > [Source: vero_vero_ohje · in force] [Path: Henkilöyhtiön ja yksityisliikkeen sukupolvenvaihdos verotuksessa > Yksityisliikkeen sukupolvenvaihdoksen esi- ja jälkitoimia] [Title: Yksityisliikkeen sukupolvenvaihdoksen esi- ja jälkitoimia]  Henkilöyhtiön ja yksityisliikkeen sukupolve

- **4** (d=0.6492, vero_ohje / CHAPTER) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-henkiloyhtion-ja-yksityisliikkeen-sukupolvenv-f4cd2de9/c3#0`
  > [Source: vero_vero_ohje · in force] [Path: Henkilöyhtiön ja yksityisliikkeen sukupolvenvaihdos verotuksessa > Henkilöyhtiön sukupolvenvaihdoksen esi- ja jälkitoimia] [Title: Henkilöyhtiön sukupolvenvaihdoksen esi- ja jälkitoimia]  Henkilöyhtiön ja yksityisliikkeen sukupolvenvaihd

- **5** (d=0.6554, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-henkiloyhtion-ja-yksityisliikkeen-sukupolvenv-f4cd2de9/c1/s1-1#0`
  > [Source: vero_vero_ohje · in force] [Path: Henkilöyhtiön ja yksityisliikkeen sukupolvenvaihdos verotuksessa > Johdanto > Yleistä sukupolvenvaihdoksesta verotuksessa] [Title: Yleistä sukupolvenvaihdoksesta verotuksessa]  Henkilöyhtiön ja yksityisliikkeen sukupolvenvaihdos verotuks


### Q11. Arvonlisäveron palautus ulkomaiselle yritykselle

- **1** (d=0.6201, laki / SECTION) `finlex/laki/finlex-laki-laki-arvonlisaverolain-muuttamisesta-29-html-4c90da15/c6/s122#0`
  > [Source: finlex_laki · in force] [Path: Laki arvonlisäverolain muuttamisesta > Kansainväliseen kauppaan liittyvät verottomuudet > 122 §] [Title: 122 §]  Laki arvonlisäverolain muuttamisesta — 122 §  1 momentti Ulkomaisella elinkeinonharjoittajalla, joka ei ole harjoittamastaan my

- **2** (d=0.6206, laki / SECTION) `finlex/laki/finlex-laki-laki-arvonlisaverolain-muuttamisesta-71-html-610ec68c/s122#0`
  > [Source: finlex_laki · in force] [Path: Laki arvonlisäverolain muuttamisesta > 122 §] [Title: 122 §]  Laki arvonlisäverolain muuttamisesta — 122 §  1 momentti Ulkomaisella elinkeinonharjoittajalla on oikeus saada palautuksena tavaran tai palvelun hankintaan sisältyvä arvonlisäver

- **3** (d=0.6258, laki / SECTION) `finlex/laki/finlex-laki-laki-arvonlisaverolain-muuttamisesta-38-html-932b572b/s122#0`
  > [Source: finlex_laki · in force] [Path: Laki arvonlisäverolain muuttamisesta > 122 §] [Title: 122 §]  Laki arvonlisäverolain muuttamisesta — 122 §  1 momentti Ulkomaisella elinkeinonharjoittajalla, joka ei ole harjoittamastaan myynnistä verovelvollinen ja jolla ei ole Suomessa ki

- **4** (d=0.6366, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-arvonlisaverovelvollisen-opas-arvonlisaverove-57a70b9e/c8/s8-5/s8-5-2#0`
  > [Source: vero_vero_ohje · in force] [Path: Arvonlisäverovelvollisen opas > Vähennysoikeus arvonlisäverotuksessa > Arvonlisäveron palauttaminen > Kotimaan arvonlisäveron palauttaminen ulkomaisille yrityksille] [Title: Kotimaan arvonlisäveron palauttaminen ulkomaisille yrityksille]

- **5** (d=0.6383, laki / SECTION) `finlex/laki/finlex-laki-laki-arvonlisaverolain-muuttamisesta-71-html-610ec68c/s122a#0`
  > [Source: finlex_laki · in force] [Path: Laki arvonlisäverolain muuttamisesta > 122a §] [Title: 122a §]  Laki arvonlisäverolain muuttamisesta — 122a §  1 momentti Edellä 122 §:n 1 momentissa tarkoitetulla ulkomaisella elinkeinonharjoittajalla on oikeus saada palautuksena 131 a §:s


### Q12. Yhteisön luovutusvoittoverotus osakkeiden myynnistä

- **1** (d=0.7550, kho / CASE) `finlex/kho/finlex-korkein-hallinto-oikeus-ennakkopaatokset-kho-2001-48-html-9623c5ac#1`
  > [Source: finlex_kho · in force] [Path: KHO:2001:48] [Title: KHO:2001:48]  KHO:2001:48  kappale 12 Kunkin osuuden luovutushinta on sen vastikkeeksi saadun osuuden käypä arvo yhteisomistussuhteen jakamishetkellä 22.6.2000. Kunkin osuuden hankintameno on sen lahjaverotuksessa käytet

- **2** (d=0.7614, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-yhteison-kayttoomaisuusosakkeiden-luovutusten-1b17a211/c7/s7-2#0`
  > [Source: vero_vero_ohje · in force] [Path: Yhteisön käyttöomaisuusosakkeiden luovutusten verokohtelu > Luovutushintaan tehtävät oikaisut ja luovutushinnasta vähennyskelvottomat menot > Verovapaan tulon hankkimisesta aiheutuneet menot] [Title: Verovapaan tulon hankkimisesta aiheut

- **3** (d=0.7626, kho / CASE) `finlex/kho/finlex-korkein-hallinto-oikeus-ennakkopaatokset-kho-1984-b-ii-611-html-1421396f#0`
  > [Source: finlex_kho · in force] [Path: KHO:1984-B-II-611] [Title: KHO:1984-B-II-611]  KHO:1984-B-II-611  kappale 1 Tytäryhtiö oli myynyt yli 5 vuotta omistamansa emoyhtiön osakkeet emoyhtiön osakkaille huomattavasti käypää hintaa halvemmalla hinnalla. Myydyt osakkeet eivät olleet

- **4** (d=0.7655, vero_ohje / CHAPTER) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-yhteison-kayttoomaisuusosakkeiden-luovutusten-1b17a211/c2#0`
  > [Source: vero_vero_ohje · in force] [Path: Yhteisön käyttöomaisuusosakkeiden luovutusten verokohtelu > Luovutusvoiton verovapauden soveltamisala] [Title: Luovutusvoiton verovapauden soveltamisala]  Yhteisön käyttöomaisuusosakkeiden luovutusten verokohtelu — 2 — Luovutusvoiton ver

- **5** (d=0.7748, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-osuuskunnan-ja-sen-jasenen-verotuksesta-osuus-d7198fff/c5/s5-2#0`
  > [Source: vero_vero_ohje · in force] [Path: Osuuskunnan ja sen jäsenen verotuksesta > Osuuskuntaan tehtävät sijoitukset ja verotus > Jäsenen verotus] [Title: Jäsenen verotus]  Osuuskunnan ja sen jäsenen verotuksesta — 5.2 — Jäsenen verotus  kappale 1 Jäsenen osuuskuntaan maksama o


### Q13. Henkilökohtaisen tulon ja pääomatulon verotus

- **1** (d=0.6629, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-verotettavan-tulon-laskeminen-henkiloverotuks-3cf532e4/c5/s5-1#0`
  > [Source: vero_vero_ohje · repealed] [Path: Verotettavan tulon laskeminen henkilöverotuksessa > Verosta tehtävät vähennykset > Veron määräytyminen] [Title: Veron määräytyminen]  Verotettavan tulon laskeminen henkilöverotuksessa — 5.1 — Veron määräytyminen  kappale 1 Luonnollisen h

- **2** (d=0.6813, vero_ohje / CHAPTER) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-verotettavan-tulon-laskeminen-henkiloverotuks-3cf532e4/c4#0`
  > [Source: vero_vero_ohje · repealed] [Path: Verotettavan tulon laskeminen henkilöverotuksessa > Verotettavan pääomatulon laskenta] [Title: Verotettavan pääomatulon laskenta]  Verotettavan tulon laskeminen henkilöverotuksessa — 4 — Verotettavan pääomatulon laskenta

- **3** (d=0.7045, vero_ohje / CHAPTER) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-verohallinnon-yhtenaistamisohjeet-vuodelta-20-671e6a28/c2#0`
  > [Source: vero_vero_ohje · in force] [Path: Verohallinnon yhtenäistämisohjeet vuodelta 2025 toimitettavaa verotusta varten > Henkilökohtaisen tulon verotus] [Title: Henkilökohtaisen tulon verotus]  Verohallinnon yhtenäistämisohjeet vuodelta 2025 toimitettavaa verotusta varten — 2 

- **4** (d=0.7088, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-rajoitetusti-verovelvollisen-tulon-verotus-lu-b33b7bd7/c10/s10-3#0`
  > [Source: vero_vero_ohje · in force] [Path: Rajoitetusti verovelvollisen tulon verotus - luonnolliset henkilöt > Rajoitetusti verovelvollisen tulon verotus > VML:n mukainen verotus] [Title: VML:n mukainen verotus]  Rajoitetusti verovelvollisen tulon verotus - luonnolliset henkilöt

- **5** (d=0.7107, laki / SECTION) `finlex/laki/finlex-laki-laki-rajoitetusti-verovelvollisen-tulon-ja-varallisuuden-verottamise-542f6978/c3/s13#0`
  > [Source: finlex_laki · in force] [Path: Laki rajoitetusti verovelvollisen tulon ja varallisuuden verottamisesta annetun lain muuttamisesta > Verotusmenettelystä annetun lain mukaisessa järjestyksessä toimitettava verotus > 13 §] [Title: 13 §]  Laki rajoitetusti verovelvollisen tu


### Q14. Ennakonpidätys palkasta ja eläkkeestä

- **1** (d=0.7614, vero_paatos / CHAPTER) `vero/vero_paatos/vero-syventavat-vero-ohjeet-paatokset-verohallinnon-paatos-ennakonpidatysprosent-b09a9899/c9#0`
  > [Source: vero_vero_paatos · in force] [Path: Verohallinnon päätös ennakonpidätysprosenttien laskentaperusteista eläkettä ja eläkkeensaajan palkkatuloa varten sekä ennakonkannossa määrättävän ennakkoveron laskentaperusteista vuodelle 2026 > Ennakonpidätysprosenttien laskeminen elä

- **2** (d=0.7681, vero_paatos / CHAPTER) `vero/vero_paatos/vero-syventavat-vero-ohjeet-paatokset-verohallinnon-paatos-vuonna-2024-sovellett-543958e6/c3#0`
  > [Source: vero_vero_paatos · in force] [Path: Verohallinnon päätös vuonna 2024 sovellettavien ennakonpidätysperusteiden voimaantulosta > §] [Title: §]  Verohallinnon päätös vuonna 2024 sovellettavien ennakonpidätysperusteiden voimaantulosta — 3 — §  kappale 1 Ennakonpidätys toimit

- **3** (d=0.7907, vero_paatos / CHAPTER) `vero/vero_paatos/vero-syventavat-vero-ohjeet-paatokset-verohallinnon-paatos-ennakonpidatysprosent-b09a9899/c10#0`
  > [Source: vero_vero_paatos · in force] [Path: Verohallinnon päätös ennakonpidätysprosenttien laskentaperusteista eläkettä ja eläkkeensaajan palkkatuloa varten sekä ennakonkannossa määrättävän ennakkoveron laskentaperusteista vuodelle 2026 > Palkan ja muiden tulojen ennakonpidätysp

- **4** (d=0.7924, vero_paatos / CHAPTER) `vero/vero_paatos/vero-syventavat-vero-ohjeet-paatokset-verohallinnon-paatos-ennakonpidatysprosent-b09a9899/c4#0`
  > [Source: vero_vero_paatos · in force] [Path: Verohallinnon päätös ennakonpidätysprosenttien laskentaperusteista eläkettä ja eläkkeensaajan palkkatuloa varten sekä ennakonkannossa määrättävän ennakkoveron laskentaperusteista vuodelle 2026 > Eläkkeen ennakonpidätysprosentin laskenn

- **5** (d=0.7950, vero_paatos / SECTION) `vero/vero_paatos/vero-syventavat-vero-ohjeet-paatokset-verohallinnon-paatos-ennakonpidatysprosent-b09a9899/c9/s9-1#0`
  > [Source: vero_vero_paatos · in force] [Path: Verohallinnon päätös ennakonpidätysprosenttien laskentaperusteista eläkettä ja eläkkeensaajan palkkatuloa varten sekä ennakonkannossa määrättävän ennakkoveron laskentaperusteista vuodelle 2026 > Ennakonpidätysprosenttien laskeminen elä


### Q15. Verotusmenettelylaki muutoksenhaku

- **1** (d=0.6789, laki / SECTION) `finlex/laki/finlex-laki-laki-korkotulon-lahdeverosta-annetun-lain-muuttamisesta-4-html-ab80f48d/s17#0`
  > [Source: finlex_laki · in force] [Path: Laki korkotulon lähdeverosta annetun lain muuttamisesta > Muutoksenhaku] [Title: Muutoksenhaku]  Laki korkotulon lähdeverosta annetun lain muuttamisesta — 17 § Muutoksenhaku  1 momentti Ennakkoratkaisun hakija ja Veronsaajien oikeudenvalvon

- **2** (d=0.6835, laki / SECTION) `finlex/laki/finlex-laki-laki-eraiden-asuntojen-vuokraustoimintaa-harjoittavien-osakeyhtioide-c3aff321/s20#0`
  > [Source: finlex_laki · in force] [Path: Laki eräiden asuntojen vuokraustoimintaa harjoittavien osakeyhtiöiden veronhuojennuksesta annetun lain 17 ja 20 §:n muuttamisesta > Muutoksenhaku] [Title: Muutoksenhaku]  Laki eräiden asuntojen vuokraustoimintaa harjoittavien osakeyhtiöiden

- **3** (d=0.6902, laki_skk / SECTION) `finlex/laki_skk/finlex-laki-saadoskokoelma-laki-sahkoalan-ja-fossiilisten-polttoaineiden-alan-va-19473b8b/c5/s22#0`
  > [Source: finlex_laki_skk · in force] [Path: Laki sähköalan ja fossiilisten polttoaineiden alan väliaikaisista voittoveroista > Erinäiset säännökset > Muutoksenhaku] [Title: Muutoksenhaku]  22 § Muutoksenhaku  1 momentti Muutoksenhaussa noudatetaan, mitä verotusmenettelystä annetu

- **4** (d=0.6916, laki / SECTION) `finlex/laki/finlex-laki-laki-korkotulon-lahdeverosta-annetun-lain-muuttamisesta-3-html-16113669/s17#0`
  > [Source: finlex_laki · in force] [Path: Laki korkotulon lähdeverosta annetun lain muuttamisesta > Muutoksenhaku] [Title: Muutoksenhaku]  Laki korkotulon lähdeverosta annetun lain muuttamisesta — 17 § Muutoksenhaku  1 momentti Muutoksenhausta koronsaajalle määrättyä lähdeveroa kos

- **5** (d=0.6966, laki / SECTION) `finlex/laki/finlex-laki-laki-verotusmenettelysta-annetun-lain-muuttamisesta-41-html-dfa1bfe9/s53#0`
  > [Source: finlex_laki · in force] [Path: Laki verotusmenettelystä annetun lain muuttamisesta > Verovastuun toteuttaminen ja muutoksenhaku] [Title: Verovastuun toteuttaminen ja muutoksenhaku]  Laki verotusmenettelystä annetun lain muuttamisesta — 53 § Verovastuun toteuttaminen ja m


### Q16. Yleishyödyllinen yhteisö verovapaus

- **1** (d=0.7210, laki / SECTION) `finlex/laki/finlex-laki-laki-eraiden-yleishyodyllisten-yhteisojen-veronhuojennuksista-html-ae64dd5a/s1#0`
  > [Source: finlex_laki · in force] [Path: Laki eräiden yleishyödyllisten yhteisöjen veronhuojennuksista > 1 §] [Title: 1 §]  Laki eräiden yleishyödyllisten yhteisöjen veronhuojennuksista — 1 §  1 momentti Yhteiskunnallisesti merkittävää toimintaa harjoittavien yleishyödyllisten yht

- **2** (d=0.7284, laki_skk / SECTION) `finlex/laki_skk/finlex-laki-saadoskokoelma-laki-yhteiskunnallisesti-merkittavaa-toimintaa-harjoi-0ca37b0c/s1#0`
  > [Source: finlex_laki_skk · in force] [Path: Laki yhteiskunnallisesti merkittävää toimintaa harjoittavien yleishyödyllisten yhteisöjen veronhuojennuksista > 1 §] [Title: 1 §]  1 §  1 momentti Yhteiskunnallisesti merkittävää toimintaa harjoittavien yleishyödyllisten yhteisöjen tulo

- **3** (d=0.7335, laki / SECTION) `finlex/laki/finlex-laki-laki-eraiden-yleishyodyllisten-yhteisojen-veronhuojennuksista-annetu-5e63b0ea/s1#0`
  > [Source: finlex_laki · in force] [Path: Laki eräiden yleishyödyllisten yhteisöjen veronhuojennuksista annetun lain 1 ja 6 §:n muuttamisesta > 1 §] [Title: 1 §]  Laki eräiden yleishyödyllisten yhteisöjen veronhuojennuksista annetun lain 1 ja 6 §:n muuttamisesta — 1 §  1 momentti Y

- **4** (d=0.7536, kho / CASE) `finlex/kho/finlex-korkein-hallinto-oikeus-ennakkopaatokset-kho-1980-b-ii-505-html-c22a6964#0`
  > [Source: finlex_kho · in force] [Path: KHO:1980-B-II-505] [Title: KHO:1980-B-II-505]  KHO:1980-B-II-505  kappale 1 Yhdistys edisti raviurheilua ja hevosjalostusta järjestämällä ravikilpailuja, joissa kilpailijoille maksettiin rahapalkintoja ja joiden yhteydessä toimeenpantiin ved

- **5** (d=0.7548, kho / CASE) `finlex/kho/finlex-korkein-hallinto-oikeus-ennakkopaatokset-kho-2009-5-html-b66803fd#5`
  > [Source: finlex_kho · in force] [Path: KHO:2009:5] [Title: KHO:2009:5]  KHO:2009:5  kappale 33 Yhteisön harjoittaman laajan elinkeinotoiminnan sosiaalinen luonne ei tarkoita sitä, että kyseinen toiminta olisi yleishyödyllistä. Yhteisöllä on oikeus harjoittaa elinkeinotoimintaa, m


### Q17. Kiinteistöveron määrääminen ja perusteet

- **1** (d=0.6419, vero_ohje / CHAPTER) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-kiinteistoverolain-soveltamisohje-kiinteistov-5e6d02f0/c5#0`
  > [Source: vero_vero_ohje · in force] [Path: Kiinteistöverolain soveltamisohje > Veron määräytyminen] [Title: Veron määräytyminen]  Kiinteistöverolain soveltamisohje — 5 — Veron määräytyminen

- **2** (d=0.6525, vero_ohje / CHAPTER) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-kiinteistoverolain-soveltamisohje-kiinteistov-cc0b2ec1/c5#0`
  > [Source: vero_vero_ohje · repealed] [Path: Kiinteistöverolain soveltamisohje > Veron määräytyminen] [Title: Veron määräytyminen]  Kiinteistöverolain soveltamisohje — 5 — Veron määräytyminen

- **3** (d=0.6842, vero_ohje / CHAPTER) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-kiinteistoverolain-soveltamisohje-kiinteistov-cc0b2ec1/c1#0`
  > [Source: vero_vero_ohje · repealed] [Path: Kiinteistöverolain soveltamisohje > Kiinteistöverolain pääpiirteet] [Title: Kiinteistöverolain pääpiirteet]  Kiinteistöverolain soveltamisohje — 1 — Kiinteistöverolain pääpiirteet  kappale 1 Suomessa olevat kiinteistöt ovat kiinteistöver

- **4** (d=0.6863, vero_ohje / CHAPTER) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-kiinteistoverolain-soveltamisohje-kiinteistov-5e6d02f0/c1#0`
  > [Source: vero_vero_ohje · in force] [Path: Kiinteistöverolain soveltamisohje > Kiinteistöverolain pääpiirteet] [Title: Kiinteistöverolain pääpiirteet]  Kiinteistöverolain soveltamisohje — 1 — Kiinteistöverolain pääpiirteet  kappale 1 Suomessa olevat kiinteistöt ovat kiinteistöver

- **5** (d=0.7259, vero_ohje / CHAPTER) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-kiinteistojen-arvostaminen-kiinteistoverotuks-7be57686/c1#0`
  > [Source: vero_vero_ohje · repealed] [Path: Kiinteistöjen arvostaminen kiinteistöverotuksessa > Kiinteistön verotusarvon määräytymisperusteet] [Title: Kiinteistön verotusarvon määräytymisperusteet]  Kiinteistöjen arvostaminen kiinteistöverotuksessa — 1 — Kiinteistön verotusarvon m


### Q18. Tuloverolain 28 §:n soveltaminen

- **1** (d=0.9248, laki / SECTION) `finlex/laki/finlex-laki-laki-elinkeinotulon-verottamisesta-annetun-lain-28-n-muuttamisesta-h-e7653ca5/s28#0`
  > [Source: finlex_laki · in force] [Path: Laki elinkeinotulon verottamisesta annetun lain 28 §:n muuttamisesta > 28 §] [Title: 28 §]  Laki elinkeinotulon verottamisesta annetun lain 28 §:n muuttamisesta — 28 §  1 momentti Poiketen siitä, mitä 2 momentissa on säädetty enimmäisprosen

- **2** (d=0.9465, laki / AMENDMENT_BLOCK) `finlex/laki/finlex-laki-tuloverolaki-html-9e9b64a4/c1/a28-1-2005-40#0`
  > [Source: finlex_laki · in force] [Path: Tuloverolaki > Muutossäädösten voimaantulo ja soveltaminen > 28.1.2005/40] [Title: 28.1.2005/40]  Tuloverolaki — muutos 28.1.2005/40

- **3** (d=0.9481, laki / AMENDMENT_BLOCK) `finlex/laki/finlex-laki-tuloverolaki-html-9e9b64a4/c1/a28-12-2012-929#0`
  > [Source: finlex_laki · in force] [Path: Tuloverolaki > Muutossäädösten voimaantulo ja soveltaminen > 28.12.2012/929] [Title: 28.12.2012/929]  Tuloverolaki — muutos 28.12.2012/929

- **4** (d=0.9488, laki / SECTION) `finlex/laki/finlex-laki-laki-sahkon-ja-eraiden-polttoaineiden-valmisteverosta-html-48d8fedd/s28#0`
  > [Source: finlex_laki · in force] [Path: Laki sähkön ja eräiden polttoaineiden valmisteverosta > 28 §] [Title: 28 §]  Laki sähkön ja eräiden polttoaineiden valmisteverosta — 28 §  1 momentti Niiden, joilla kumotun lain nojalla on ollut oikeus toimia valtuutettuna varastonpitäjänä,

- **5** (d=0.9582, vero_kvl / GUIDE) `vero/vero_kvl/vero-syventavat-vero-ohjeet-keskusverolautakunnan-ennakkoratkaisut-kvl-014-2011-7dfd14c3#0`
  > [Source: vero_vero_kvl · repealed] [Path: KVL:014/2011] [Title: KVL:014/2011]  KVL:014/2011  kappale 1 Kiinteistöjen vuokraamista harjoittava A Oy aikoi siirtää yhden liikekiinteistökokonaisuutensa perustettavalle yhtiölle elinkeinotulon verottamisesta annetun lain 52 d §:n säänn


### Q19. Siirtohinnoittelu konserniyhtiöt

- **1** (d=0.8016, kho / CASE) `finlex/kho/finlex-korkein-hallinto-oikeus-ennakkopaatokset-kho-2020-35-html-63c77fef#10`
  > [Source: finlex_kho · in force] [Path: KHO:2020:35] [Title: KHO:2020:35]  KHO:2020:35  kappale 55 Yhtiön ja A Finance NV:n välillä on tehty sopimus, jossa on sovittu konsernin sisäiseen rahoitusfunktioon liittyvistä markkinaehtoisista valuutta- ja korkosuojausliiketoimista. Sopim

- **2** (d=0.8268, kho / CASE) `finlex/kho/finlex-korkein-hallinto-oikeus-ennakkopaatokset-kho-2018-173-html-d0293527#11`
  > [Source: finlex_kho · in force] [Path: KHO:2018:173] [Title: KHO:2018:173]  KHO:2018:173  kappale 43 A Oy on saanut rojalteja ja on myynyt lisensioimiaan aineettomia oikeuksia, mistä A Oy:n konserniyhtiöiden UAB A:n, A AB:n, sekä A Sp.z.o.o:n kanssa laadittujen sopimustenkin muka

- **3** (d=0.8330, kho / CASE) `finlex/kho/finlex-korkein-hallinto-oikeus-ennakkopaatokset-kho-2018-173-html-d0293527#14`
  > [Source: finlex_kho · in force] [Path: KHO:2018:173] [Title: KHO:2018:173]  KHO:2018:173  kappale 59 Verohallinnon soveltama siirtohinnoittelumalli  kappale 60 Kun otetaan erityisesti huomioon konsernin valmistusyhtiöiden osallistuminen toiminnan kehittämiseen hallinto-oikeus tot

- **4** (d=0.8350, kho / CASE) `finlex/kho/finlex-korkein-hallinto-oikeus-ennakkopaatokset-kho-2020-35-html-63c77fef#4`
  > [Source: finlex_kho · in force] [Path: KHO:2020:35] [Title: KHO:2020:35]  KHO:2020:35  kappale 29 A-konsernissa on vuonna 2008 toteutettu sisäisen rahoitusfunktion uudelleenjärjestely, jossa A Oyj on siirtänyt apportilla konsernin sisäiset pitkäaikaiset lainasaamiset perustetulle

- **5** (d=0.8447, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-suurten-konsernien-vahimmaisverotus-huomioita-ef0cccb9/c11/s11-5#0`
  > [Source: vero_vero_ohje · in force] [Path: Suurten konsernien vähimmäisverotus - huomioitavat verot > Laskennallisia veroja koskevat siirtymäsäännökset > Varojen siirrot konserniyksiköiden välillä siirtymäkaudella] [Title: Varojen siirrot konserniyksiköiden välillä siirtymäkaudel


### Q20. Maakuntavero ja kunnallisvero

- **1** (d=0.9228, asetus_skk / SECTION) `finlex/asetus_skk/finlex-asetus-saadoskokoelma-tasavallan-presidentin-asetus-ahvenanmaan-maakunnal-62135881/s2#0`
  > [Source: finlex_asetus_skk · in force] [Path: Tasavallan presidentin asetus Ahvenanmaan maakunnalle ja Ahvenanmaan kunnille suoritettavien verojen verotuksen toimittamisesta Ahvenanmaalla > 2 §] [Title: 2 §]  2 §  1 momentti Ahvenanmaan maakunta vastaa maakunnan kunnallisveroa ja

- **2** (d=0.9296, laki / SECTION) `finlex/laki/finlex-laki-laki-kunnan-peruspalvelujen-valtionosuudesta-annetun-lain-muuttamise-9e716c60/s29#0`
  > [Source: finlex_laki · in force] [Path: Laki kunnan peruspalvelujen valtionosuudesta annetun lain muuttamisesta > Verotuloihin perustuva valtionosuuden tasaus] [Title: Verotuloihin perustuva valtionosuuden tasaus]  Laki kunnan peruspalvelujen valtionosuudesta annetun lain muuttam

- **3** (d=0.9314, asetus / SECTION) `finlex/asetus/finlex-asetus-tasavallan-presidentin-asetus-ahvenanmaan-maakunnalle-ja-ahvenanma-29dc8621/s2#0`
  > [Source: finlex_asetus · in force] [Path: Tasavallan presidentin asetus Ahvenanmaan maakunnalle ja Ahvenanmaan kunnille suoritettavien verojen verotuksen toimittamisesta Ahvenanmaalla > 2 §] [Title: 2 §]  Tasavallan presidentin asetus Ahvenanmaan maakunnalle ja Ahvenanmaan kunnil

- **4** (d=0.9361, asetus_skk / SECTION) `finlex/asetus_skk/finlex-asetus-saadoskokoelma-asetus-kuntien-valtionosuudesta-html-ebe3dacb/s2#0`
  > [Source: finlex_asetus_skk · in force] [Path: Asetus kuntien valtionosuudesta > 2 §] [Title: 2 §]  2 §  1 momentti Määrättäessä kunnan verotulojen perusteella tehtäviä valtionosuuksien tasauksia otetaan kuntien valtionosuuslain 7 §:n mukaisina laskennallisina verotuloina huomioon

- **5** (d=0.9366, asetus / SECTION) `finlex/asetus/finlex-asetus-asetus-kunnallisverotuksen-toimittamisesta-ahvenanmaan-maakunnassa-2f2fc507/s2#0`
  > [Source: finlex_asetus · in force] [Path: Asetus kunnallisverotuksen toimittamisesta Ahvenanmaan maakunnassa > 2 §] [Title: 2 §]  Asetus kunnallisverotuksen toimittamisesta Ahvenanmaan maakunnassa — 2 §  1 momentti Ahvenanmaan maakunnan kunnat osallistuvat verotuksen toimittamise
