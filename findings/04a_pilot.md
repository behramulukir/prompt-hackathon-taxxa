# 04a Pilot — spot-check findings

Pilot vector store: `output/lancedb_pilot` with 1000 chunks. 10 Finnish tax queries, top-5 results each. Lower distance = closer.

## Assessment

Spot-check criterion from 4a.3: *"For at least 7 of 10 queries, top-3 results contain at least one plausibly-relevant chunk."*

| Q | Topic                                  | Top-3 has plausibly-relevant? | Notes |
|---|----------------------------------------|------------------------------|-------|
| 1 | Arvonlisäveron vähennysoikeus          | ✓ | KHO:2025:20 + ALV 210 § + Liikevaihtoverolaki 66 § |
| 2 | Verovähennys yritystoiminnan kuluista  | ✓ | R&D yhdistelmävähennys + KHO 1986-B-II-520 |
| 3 | Kuolinpesän verotus ja jälkiverotus    | ✓ | Kuolinpesään kohdistettu veron määrääminen |
| 4 | Kiinteä toimipaikka verosopimuksessa   | ✓ | All top-5 are treaty §5/§7 hits |
| 5 | Asianomistajan oikeus nostaa syyte     | ~ marginal | Top-3 are civil-procedure §s; rikoslaki only at #4 |
| 6 | KHO arvonlisävero päätös               | ✓ | KHO 2025/2021/2001 VAT cases |
| 7 | Vero-ohje työsuhde-edun verotus        | ✓ | Työsuhdeoptio, työtulon laskenta |
| 8 | Säädöskokoelma muutos arvonlisäverolakiin | ✓ | Arvonlisäverolaki AMENDMENT_BLOCK at #1 |
| 9 | Verovapaa lahja perintö                | ✓ | Veronkierto välilahjoitus, lahjavero, lahjojen kumulointi |
| 10 | Yrityksen sukupolvenvaihdos           | ✓ | Henkilöyhtiön ja yksityisliikkeen sukupolvenvaihdos |

**Score: 9/10 plausibly-relevant in top-3.** Pilot passes the spot-check.

Observations:
- All 1000 vectors non-zero. `in_force` populated for 1000/1000 (Step 3 enriched everything).
- Asymmetric query/document encoding (input_type='query' for the question, 'document' for chunks) is in place and producing tight clusters of relevant hits.
- For Q5, the only marginal query, the model picks up "asianosaisten oikeus" (party rights in civil proc.) before "asianomistaja" (aggrieved party in criminal proc.) — these are Finnish-specific near-synonyms that even good embeddings confuse. Not a corpus problem.

### Token usage on pilot

- 1000 chunks → **540,616 tokens** embedded ⇒ ~540 tokens/chunk average (including hierarchy prefix).
- Raw chunk avg (no prefix, sampled): ~275 tokens. Prefix overhead adds ~265 tokens.
- **Extrapolated full corpus: ~217M tokens** — *over* the 200M free tier by ~17M.
- The doc's estimate was 147M with 36% headroom. Reality is higher; the dry-run on the full corpus will give exact numbers.




## Q1. Mikä on arvonlisäveron vähennysoikeus?

- **1** (d=0.7726, kho / CASE) `finlex/kho/finlex-korkein-hallinto-oikeus-ennakkopaatokset-kho-2025-20-html-1d214bbf#2`
  > [Source: finlex_kho · in force] [Path: KHO:2025:20] [Title: KHO:2025:20]  KHO:2025:20  kappale 24 (17) Asiassa on tarkoituksenmukaista ensin ratkaista, onko keskusverolautakunnan soveltaman arvonlisäverodirektiivin säännöksen tulkinnasta pyydettävä unionin tuomioistuimen ennakkoratkaisu. Tämän jälke

- **2** (d=0.8077, laki / SECTION) `finlex/laki/finlex-laki-laki-arvonlisaverolain-210-n-muuttamisesta-1-html-615d6c4e/s210#0`
  > [Source: finlex_laki · in force] [Path: Laki arvonlisäverolain 210 §:n muuttamisesta > 210 §] [Title: 210 §]  Laki arvonlisäverolain 210 §:n muuttamisesta — 210 §  1 momentti Verovirasto tai, jos tulliviranomainen on kantanut veron, tullihallitus voi erityisestä syystä hakemuksesta alentaa suoritett

- **3** (d=0.8199, laki / SECTION) `finlex/laki/finlex-laki-liikevaihtoverolaki-html-4bf2bce4/c11/s66#0`
  > [Source: finlex_laki · in force] [Path: Liikevaihtoverolaki > Ajallinen kohdistaminen > 66 짠] [Title: 66 짠]  Liikevaihtoverolaki — 66 § 66 짠  1 momentti Verovelvollinen, jolla kirjanpitolain mukaan on oikeus pit채채 maksuperusteista kirjanpitoa, saa tehd채 v채hennyksen silt채 kalenterikuukaudelta, jonka 

- **4** (d=0.8669, vero_ohje / CHAPTER) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-kulkuneuvojen-paikoitusta-varten-tapahtuva-al-6fbf048a/c6#1`
  > [Source: vero_vero_ohje · repealed] [Path: Kulkuneuvojen paikoitusta varten tapahtuva alueiden vuokraus arvonlisäverotuksessa > Henkilökuntapysäköinti] [Title: Henkilökuntapysäköinti]  Kulkuneuvojen paikoitusta varten tapahtuva alueiden vuokraus arvonlisäverotuksessa — 6 — Henkilökuntapysäköinti  ka

- **5** (d=0.8824, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-verotuksen-muutokset-kun-suoritus-katsotaan-j-42251a4e/c3/s3-4#0`
  > [Source: vero_vero_ohje · repealed] [Path: Verotuksen muutokset, kun suoritus katsotaan jälkikäteen palkaksi > Keskeiset säännökset > Arvonlisäverotusta koskevat säännökset] [Title: Arvonlisäverotusta koskevat säännökset]  Verotuksen muutokset, kun suoritus katsotaan jälkikäteen palkaksi — 3.4 — Arv


## Q2. Verovähennys yritystoiminnan kuluista

- **1** (d=0.7468, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-tutkimus-ja-kehittamistoiminnan-yhdistelmavah-f523f6ef/c5/s5-1#1`
  > [Source: vero_vero_ohje · in force] [Path: Tutkimus- ja kehittämistoiminnan yhdistelmävähennys > Lisävähennysten määrä > Yleisen lisävähennyksen määrä] [Title: Yleisen lisävähennyksen määrä]  Tutkimus- ja kehittämistoiminnan yhdistelmävähennys — 5.1 — Yleisen lisävähennyksen määrä  Esimerkki Esimerk

- **2** (d=0.7943, kho / CASE) `finlex/kho/finlex-korkein-hallinto-oikeus-ennakkopaatokset-kho-1986-b-ii-520-html-62ffd399#0`
  > [Source: finlex_kho · in force] [Path: KHO:1986-B-II-520] [Title: KHO:1986-B-II-520]  KHO:1986-B-II-520  kappale 1 Yhtiö oli saanut verovapaaksi säädettyä elokuvan tuotantotukea tuottamiaan elokuvia varten. Koska elokuvien valmistuskustannukset kohdistuivat veronalaisten esitystulojen hankkimiseen, 

- **3** (d=0.8446, laki / SECTION) `finlex/laki/finlex-laki-liikevaihtoverolaki-html-4bf2bce4/c11/s66#0`
  > [Source: finlex_laki · in force] [Path: Liikevaihtoverolaki > Ajallinen kohdistaminen > 66 짠] [Title: 66 짠]  Liikevaihtoverolaki — 66 § 66 짠  1 momentti Verovelvollinen, jolla kirjanpitolain mukaan on oikeus pit채채 maksuperusteista kirjanpitoa, saa tehd채 v채hennyksen silt채 kalenterikuukaudelta, jonka 

- **4** (d=0.8525, kho / CASE) `finlex/kho/finlex-korkein-hallinto-oikeus-ennakkopaatokset-kho-1980-b-ii-633-html-5c851d88#0`
  > [Source: finlex_kho · in force] [Path: KHO:1980-B-II-633] [Title: KHO:1980-B-II-633]  KHO:1980-B-II-633  kappale 1 Yhtiö muutti kaupungilta vuokraamansa varastohallin lihankäsittelyhalliksi. Ainoastaan hallin ulkoseinät käytettiin hyväksi. Työn kustannuksista ei saanut liikevaihtoverolain 18 a §:ssä

- **5** (d=0.8634, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-tutkimus-ja-kehittamistoiminnan-yhdistelmavah-f523f6ef/c5/s5-2#0`
  > [Source: vero_vero_ohje · in force] [Path: Tutkimus- ja kehittämistoiminnan yhdistelmävähennys > Lisävähennysten määrä > Ylimääräisen lisävähennyksen määrä] [Title: Ylimääräisen lisävähennyksen määrä]  Tutkimus- ja kehittämistoiminnan yhdistelmävähennys — 5.2 — Ylimääräisen lisävähennyksen määrä  ka


## Q3. Kuolinpesän verotus ja jälkiverotus

- **1** (d=0.8891, laki_skk / SECTION) `finlex/laki_skk/finlex-laki-saadoskokoelma-laki-oma-aloitteisten-verojen-verotusmenettelysta-htm-ce5b2b0c/c8/s49#0`
  > [Source: finlex_laki_skk · in force] [Path: Laki oma-aloitteisten verojen verotusmenettelystä > Veron määrääminen ja päätöksen oikaisu > Kuolinpesään kohdistettu veron määrääminen ja oikaisu] [Title: Kuolinpesään kohdistettu veron määrääminen ja oikaisu]  49 § Kuolinpesään kohdistettu veron määräämi

- **2** (d=1.0076, laki / SECTION) `finlex/laki/finlex-laki-laki-sairausvakuutuslain-34-n-muuttamisesta-html-24ca2803/s34#0`
  > [Source: finlex_laki · in force] [Path: Laki sairausvakuutuslain 34 §:n muuttamisesta > 34 §] [Title: 34 §]  Laki sairausvakuutuslain 34 §:n muuttamisesta — 34 §  1 momentti Erillisenä verovelvollisena verotettavan kuolinpesän veroäyreistä otetaan pesän osakkaalle määrättävän vakuutusmaksun perustee

- **3** (d=1.0860, vero_ohje / CHAPTER) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-ensin-kuolleen-puolison-tai-lesken-jalkeisess-b82bb53a/c5#0`
  > [Source: vero_vero_ohje · in force] [Path: Ensin kuolleen puolison tai lesken jälkeisessä perintöverotuksessa tarvittavat tiedot > Puutteelliset asiakirjat ja arvioiminen] [Title: Puutteelliset asiakirjat ja arvioiminen]  Ensin kuolleen puolison tai lesken jälkeisessä perintöverotuksessa tarvittavat

- **4** (d=1.1712, laki / SECTION) `finlex/laki/finlex-laki-laki-varainsiirtoverolain-muuttamisesta-8-html-4c75de5d/c5/s36b#0`
  > [Source: finlex_laki · in force] [Path: Laki varainsiirtoverolain muuttamisesta > Valvonta sekä veron määrääminen ja päätöksen oikaisu > Myöhästymismaksu] [Title: Myöhästymismaksu]  Laki varainsiirtoverolain muuttamisesta — 36b § Myöhästymismaksu  1 momentti Verohallinto määrää verovelvolliselle tai

- **5** (d=1.1789, kho / CASE) `finlex/kho/finlex-korkein-hallinto-oikeus-ennakkopaatokset-kho-2002-17-html-d8ebb134#0`
  > [Source: finlex_kho · in force] [Path: KHO:2002:17] [Title: KHO:2002:17]  KHO:2002:17  kappale 1 Vuonna 2000 kuolleen perinnönjättäjän jälkeen toimitettavassa perintöverotuksessa, perintö- ja lahjaverolain 55 §:ssä tarkoitettua veronhuojennusta laskettaessa, tuli pesään kuuluneiden yritysosakkeiden 


## Q4. Kiinteä toimipaikka kansainvälisessä verosopimuksessa

- **1** (d=0.7032, treaty / SECTION) `finlex/treaty/finlex-tuloverosopimukset-pohjois-makedonia-sopimus-suomen-hallituksen-ja-makedo-01ad9db3/s5-artikla-kiintea-toimipaikka#0`
  > [Source: finlex_treaty · in force] [Path: Sopimus Suomen hallituksen ja Makedonian hallituksen välillä tuloveroja koskevan kaksinkertaisen verotuksen välttämiseksi > 5 artikla - Kiinteä toimipaikka] [Title: 5 artikla - Kiinteä toimipaikka]  Sopimus Suomen hallituksen ja Makedonian hallituksen välill

- **2** (d=0.7960, treaty / SECTION) `finlex/treaty/finlex-tuloverosopimukset-israel-sopimus-suomen-tasavallan-ja-israelin-valtion-v-85e05438/s7-artikla-liiketulo#0`
  > [Source: finlex_treaty · in force] [Path: Sopimus Suomen tasavallan ja Israelin valtion välillä tulo- ja varallisuusveroja koskevan kaksinkertaisen verotuksen välttämiseksi ja veron kiertämisen estämiseksi > 7 artikla - Liiketulo] [Title: 7 artikla - Liiketulo]  Sopimus Suomen tasavallan ja Israelin

- **3** (d=0.8124, treaty / SECTION) `finlex/treaty/finlex-tuloverosopimukset-marokko-sopimus-suomen-tasavallan-ja-marokon-kuningask-68e35041/s7-artikla-liiketulo#0`
  > [Source: finlex_treaty · in force] [Path: Sopimus Suomen tasavallan ja Marokon kuningaskunnan välillä tuloveroja koskevan kaksinkertaisen verotuksen välttämiseksi ja veron kiertämisen estämiseksi > 7 artikla - Liiketulo] [Title: 7 artikla - Liiketulo]  Sopimus Suomen tasavallan ja Marokon kuningasku

- **4** (d=0.8138, treaty / SECTION) `finlex/treaty/finlex-tuloverosopimukset-thaimaa-suomen-tasavallan-hallituksen-ja-thaimaan-kuni-69c7c99c/s7-artikla-liiketulo#0`
  > [Source: finlex_treaty · in force] [Path: Suomen tasavallan hallituksen ja Thaimaan Kuningaskunnan hallituksen välinen sopimus tuloveroja koskevan kaksinkertaisen verotuksen välttämiseksi ja veron kiertämisen estämiseksi > 7 artikla - Liiketulo] [Title: 7 artikla - Liiketulo]  Suomen tasavallan hall

- **5** (d=0.8142, treaty / SECTION) `finlex/treaty/finlex-tuloverosopimukset-sambia-suomen-ja-sambian-valinen-sopimus-tulo-ja-varal-bef9689f/s7-artikla-liiketulo#0`
  > [Source: finlex_treaty · in force] [Path: Suomen ja Sambian välinen sopimus tulo- ja varallisuusveroja koskevan kaksinkertaisen verotuksen välttämiseksi ja veron kiertämisen estämiseksi > 7 artikla - Liiketulo] [Title: 7 artikla - Liiketulo]  Suomen ja Sambian välinen sopimus tulo- ja varallisuusver


## Q5. Asianomistajan oikeus nostaa syyte

- **1** (d=1.0911, laki / SECTION) `finlex/laki/finlex-laki-laki-oikeudenkaymiskaaren-muuttamisesta-40-html-8a422a02/c12/s24#0`
  > [Source: finlex_laki · in force] [Path: Laki oikeudenkäymiskaaren muuttamisesta. > Asianosaisista. > 24 §] [Title: 24 §]  Laki oikeudenkäymiskaaren muuttamisesta. — 24 §  1 momentti Asianosainen, joka on määrätty tuotavaksi asian jatkokäsittelyyn, saadaan niin hyvissä ajoin kuin se on välttämätöntä 

- **2** (d=1.1073, laki / SECTION) `finlex/laki/finlex-laki-laki-eraiden-luotonantajien-rekisteroinnista-annetun-lain-muuttamise-f1c86ab4/s10a#0`
  > [Source: finlex_laki · in force] [Path: Laki eräiden luotonantajien rekisteröinnistä annetun lain muuttamisesta > Valvontaviranomaisen tiedonsaantioikeus] [Title: Valvontaviranomaisen tiedonsaantioikeus]  Laki eräiden luotonantajien rekisteröinnistä annetun lain muuttamisesta — 10a § Valvontaviranom

- **3** (d=1.1108, laki / SECTION) `finlex/laki/finlex-laki-laki-kansanelakelain-muuttamisesta-43-html-1e45095e/s74c#0`
  > [Source: finlex_laki · in force] [Path: Laki kansaneläkelain muuttamisesta > 74c §] [Title: 74c §]  Laki kansaneläkelain muuttamisesta — 74c §  1 momentti Jos lisäosan saajalle on takautuvasti myönnetty 26 §:n 1 momentissa tarkoitettu etuus tai tällaista etuutta on korotettu, eläkelaitos voi, riippu

- **4** (d=1.1136, laki_skk / SECTION) `finlex/laki_skk/finlex-laki-saadoskokoelma-rikoslaki-html-3661a4c0/c27/s5#0`
  > [Source: finlex_laki_skk · in force] [Path: Rikoslaki > Kunnianloukkauksesta > 5 §] [Title: 5 §]  5 §  1 momentti Sillä, jota syytetään tässä luvussa mainitusta kunnianloukkauksesta, olkoon oikeus näyttää soimauksensa toteen, jos hän tarjoutuu todistamaan nimitetyn teon; ja tapahtukoon toteennäyttö 

- **5** (d=1.1169, laki / SECTION) `finlex/laki/finlex-laki-laki-esitutkintalain-2-luvun-6-n-muuttamisesta-1-html-43fbb2b0/c2/s6#0`
  > [Source: finlex_laki · in force] [Path: Laki esitutkintalain 2 luvun 6 §:n muuttamisesta > Esitutkintaan osalliset > Avustaja ja tukihenkilö] [Title: Avustaja ja tukihenkilö]  Laki esitutkintalain 2 luvun 6 §:n muuttamisesta — 6 § Avustaja ja tukihenkilö  1 momentti Rikoslain (39/1889) 20 luvun 9 ja


## Q6. Korkein hallinto-oikeus arvonlisävero KHO päätös

- **1** (d=0.9058, kho / CASE) `finlex/kho/finlex-korkein-hallinto-oikeus-ennakkopaatokset-kho-2025-20-html-1d214bbf#2`
  > [Source: finlex_kho · in force] [Path: KHO:2025:20] [Title: KHO:2025:20]  KHO:2025:20  kappale 24 (17) Asiassa on tarkoituksenmukaista ensin ratkaista, onko keskusverolautakunnan soveltaman arvonlisäverodirektiivin säännöksen tulkinnasta pyydettävä unionin tuomioistuimen ennakkoratkaisu. Tämän jälke

- **2** (d=0.9200, kho / CASE) `finlex/kho/finlex-korkein-hallinto-oikeus-ennakkopaatokset-kho-2021-63-html-78ce3061#5`
  > [Source: finlex_kho · in force] [Path: KHO:2021:63] [Title: KHO:2021:63]  KHO:2021:63  kappale 46 Tämän vuoksi Verohallinnon verotuksen oikaisupäätös 13.4.2017, Helsingin hallinto-oikeuden päätös 16.12.2016 nro 16/1246/6 ja Verohallinnon päätös 2.10.2015 on purettava hallintolainkäyttölain 63 §:n 1 

- **3** (d=0.9417, kho / CASE) `finlex/kho/finlex-korkein-hallinto-oikeus-ennakkopaatokset-kho-2001-46-html-606ff89b#0`
  > [Source: finlex_kho · in force] [Path: KHO:2001:46] [Title: KHO:2001:46]  KHO:2001:46  kappale 1 Yhtiö myi ryhmille tarkoitettuja tapahtumapaketteja, joihin sisältyi ryhmien kuljetus merellä yhtiön veneellä, ruokailu ja erilaista ohjelmaa. Aluksen käytöstä miehistöineen yhtiö veloitti aikaveloituspe

- **4** (d=0.9592, laki / SECTION) `finlex/laki/finlex-laki-laki-arvonlisaverolain-210-n-muuttamisesta-1-html-615d6c4e/s210#0`
  > [Source: finlex_laki · in force] [Path: Laki arvonlisäverolain 210 §:n muuttamisesta > 210 §] [Title: 210 §]  Laki arvonlisäverolain 210 §:n muuttamisesta — 210 §  1 momentti Verovirasto tai, jos tulliviranomainen on kantanut veron, tullihallitus voi erityisestä syystä hakemuksesta alentaa suoritett

- **5** (d=0.9722, kho / CASE) `finlex/kho/finlex-korkein-hallinto-oikeus-ennakkopaatokset-kho-2023-30-html-fed344e3#7`
  > [Source: finlex_kho · in force] [Path: KHO:2023:30] [Title: KHO:2023:30]  KHO:2023:30  kappale 48 (43) EUT:n yhdistetyissรค asioissa C-536/08 ja C-539/08 antaman tuomion perusteella yhteisรถhankinnan arvonlisรคveroa ei voida vรคhentรครค yhteisรถhankinnan turvaverkkosรครคnnรถksen soveltamistilanteess


## Q7. Vero-ohje työsuhde-edun verotus

- **1** (d=0.8622, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-tyosuhdeoption-ja-tyosuhteeseen-perustuvan-os-a76d1a6c/c4/s4-3#0`
  > [Source: vero_vero_ohje · in force] [Path: Työsuhdeoption ja työsuhteeseen perustuvan osakeannin verotus kansainvälisissä tilanteissa > Rajoitetusti verovelvollisena käytetty optio > Verotusmenettelystä annetun lain mukainen verotus] [Title: Verotusmenettelystä annetun lain mukainen verotus]  Työsuh

- **2** (d=0.8673, vero_ohje / CHAPTER) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-verotettavan-tulon-laskeminen-henkiloverotuks-3cf532e4/c2#0`
  > [Source: vero_vero_ohje · repealed] [Path: Verotettavan tulon laskeminen henkilöverotuksessa > Verotettavan ansiotulon laskenta] [Title: Verotettavan ansiotulon laskenta]  Verotettavan tulon laskeminen henkilöverotuksessa — 2 — Verotettavan ansiotulon laskenta

- **3** (d=0.8767, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-tyosta-valittomasti-johtuvat-kustannukset-enn-a0b7e669/c3/s3-2#0`
  > [Source: vero_vero_ohje · in force] [Path: Työstä välittömästi johtuvat kustannukset ennakkoperinnässä > Välittömien kustannusten huomioiminen ennakonpidätystä toimitettaessa > Työnantaja korvaa kustannukset palkansaajalle] [Title: Työnantaja korvaa kustannukset palkansaajalle]  Työstä välittömästi 

- **4** (d=0.9023, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-tyosuhdeoptioiden-verotus-tyosuhdeoptioiden-v-f9f35eaa/c2/s2-4/s2-4-2#0`
  > [Source: vero_vero_ohje · in force] [Path: Työsuhdeoptioiden verotus > Työsuhdeoptio palkansaajan tuloverotuksessa > Optiosta saadun edun arvostaminen > Työsuhdeoption myyminen] [Title: Työsuhdeoption myyminen]  Työsuhdeoptioiden verotus — 2.4.2 — Työsuhdeoption myyminen  kappale 1 Palkansaajalla sa

- **5** (d=0.9063, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-tyosuhteen-paattymiseen-liittyvien-suorituste-145523cb/c16/s16-1/s16-1-2#0`
  > [Source: vero_vero_ohje · repealed] [Path: Työsuhteen päättymiseen liittyvien suoritusten verotus > Kansainväliset tilanteet > Yleisesti verovelvollisen saama suoritus > Verosopimusten vaikutus] [Title: Verosopimusten vaikutus]  Työsuhteen päättymiseen liittyvien suoritusten verotus — 16.1.2 — Veros


## Q8. Säädöskokoelma muutos arvonlisäverolakiin

- **1** (d=0.5730, laki / AMENDMENT_BLOCK) `finlex/laki/finlex-laki-arvonlisaverolaki-html-ba5d8e0e/c1/a8-12-2006-1103#0`
  > [Source: finlex_laki · in force] [Path: Arvonlisäverolaki > Muutossäädösten voimaantulo ja soveltaminen > 8.12.2006/1103] [Title: 8.12.2006/1103]  Arvonlisäverolaki — muutos 8.12.2006/1103

- **2** (d=0.7402, laki / SECTION) `finlex/laki/finlex-laki-laki-arvonlisaverolain-210-n-muuttamisesta-1-html-615d6c4e/s210#0`
  > [Source: finlex_laki · in force] [Path: Laki arvonlisäverolain 210 §:n muuttamisesta > 210 §] [Title: 210 §]  Laki arvonlisäverolain 210 §:n muuttamisesta — 210 §  1 momentti Verovirasto tai, jos tulliviranomainen on kantanut veron, tullihallitus voi erityisestä syystä hakemuksesta alentaa suoritett

- **3** (d=0.7775, laki / SECTION) `finlex/laki/finlex-laki-laki-arpajaisverolain-1-a-n-muuttamisesta-html-8550cc54/s1a#0`
  > [Source: finlex_laki · in force] [Path: Laki arpajaisverolain 1 a §:n muuttamisesta > Muiden lakien soveltaminen] [Title: Muiden lakien soveltaminen]  Laki arpajaisverolain 1 a §:n muuttamisesta — 1a § Muiden lakien soveltaminen  1 momentti Sen lisäksi, mitä tässä laissa säädetään, arpajaisveron ver

- **4** (d=0.7804, laki / SECTION) `finlex/laki/finlex-laki-laki-korkotulon-lahdeverosta-annetun-lain-1-a-n-muuttamisesta-html-47a8f623/s1a#0`
  > [Source: finlex_laki · in force] [Path: Laki korkotulon lähdeverosta annetun lain 1 a §:n muuttamisesta > Muiden lakien soveltaminen] [Title: Muiden lakien soveltaminen]  Laki korkotulon lähdeverosta annetun lain 1 a §:n muuttamisesta — 1a § Muiden lakien soveltaminen  1 momentti Tässä laissa tarkoi

- **5** (d=0.7901, laki / LAW) `finlex/laki/finlex-laki-laki-arvonlisaverolain-muuttamisesta-annetun-lain-voimaantulosaannok-ca862f73#1`
  > [Source: finlex_laki · in force] [Path: Laki arvonlisäverolain muuttamisesta annetun lain voimaantulosäännöksen muuttamisesta] [Title: Laki arvonlisäverolain muuttamisesta annetun lain voimaantulosäännöksen muuttamisesta]  Laki arvonlisäverolain muuttamisesta annetun lain voimaantulosäännöksen muutt


## Q9. Verovapaa lahja perintö

- **1** (d=0.8655, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-veronkiertosaannoksen-soveltaminen-veronkiert-e01738df/c3/s3-5#0`
  > [Source: vero_vero_ohje · in force] [Path: Veronkiertosäännöksen soveltaminen > Veroetujen tavoittelu erilaisissa luovutustilanteissa > Välilahjoitukset perhepiirissä ennen omaisuuden luovutusta] [Title: Välilahjoitukset perhepiirissä ennen omaisuuden luovutusta]  Veronkiertosäännöksen soveltaminen 

- **2** (d=0.8971, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-osakeyhtion-sukupolvenvaihdos-verotuksessa-os-08fb843d/c2/s2-4/s2-4-2#1`
  > [Source: vero_vero_ohje · repealed] [Path: Osakeyhtiön sukupolvenvaihdos verotuksessa > Osakeyhtiön osakkeiden luovutus > Osakkeiden ostajan tai saajan lahjaverotus > Lahjaveron alainen saanto] [Title: Lahjaveron alainen saanto]  Osakeyhtiön sukupolvenvaihdos verotuksessa — 2.4.2 — Lahjaveron alaine

- **3** (d=0.9014, vero_ohje / CHAPTER) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-lahjojen-kumulointi-lahjojen-kumulointi-vero-234f3e96/c7#2`
  > [Source: vero_vero_ohje · in force] [Path: Lahjojen kumulointi > Sukupolvenvaihdoshuojennuksen kumulointi] [Title: Sukupolvenvaihdoshuojennuksen kumulointi]  Lahjojen kumulointi — 7 — Sukupolvenvaihdoshuojennuksen kumulointi  Esimerkki Huomio osio alkaa Esimerkki 6: Isä antaa tyttärelleen lahjaksi o

- **4** (d=0.9053, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-perinto-ja-lahjaverotus-kansainvalisissa-tila-d80892ae/c4/s4-9/s4-9-5#0`
  > [Source: vero_vero_ohje · in force] [Path: Perintö- ja lahjaverotus kansainvälisissä tilanteissa > Ulkomailta Suomeen tullut perintö tai lahja > Verosopimuksilla perintöverosta vapautettu omaisuus > Perinnönjättäjä tai lahjanantaja asui Ruotsissa tai Norjassa ennen verosopimuksen päättymistä] [Title

- **5** (d=0.9069, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-omaisuuden-luovutusvoitot-ja-tappiot-luonnoll-9caa22ae/c11/s11-1/s11-1-9#0`
  > [Source: vero_vero_ohje · repealed] [Path: Omaisuuden luovutusvoitot ja -tappiot luonnollisen henkilön tuloverotuksessa > Vastikkeettomat ja alihintaiset saannot > Perintönä, testamentilla tai lahjana saadun omaisuuden luovutusvoiton verotus > Lahjana saadun omaisuuden luovuttaminen vuoden kuluttua 


## Q10. Yrityksen sukupolvenvaihdos verotuksellisesti

- **1** (d=0.7928, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-henkiloyhtion-ja-yksityisliikkeen-sukupolvenv-f4cd2de9/c4/s4-2/s4-2-1#0`
  > [Source: vero_vero_ohje · in force] [Path: Henkilöyhtiön ja yksityisliikkeen sukupolvenvaihdos verotuksessa > Yksityisliikkeen sukupolvenvaihdos > Elinkeinotoiminnan luovuttajan tuloverotus > Elinkeinotoiminnan tulon laskeminen] [Title: Elinkeinotoiminnan tulon laskeminen]  Henkilöyhtiön ja yksityis

- **2** (d=0.8301, kho / CASE) `finlex/kho/finlex-korkein-hallinto-oikeus-ennakkopaatokset-kho-2002-17-html-d8ebb134#0`
  > [Source: finlex_kho · in force] [Path: KHO:2002:17] [Title: KHO:2002:17]  KHO:2002:17  kappale 1 Vuonna 2000 kuolleen perinnönjättäjän jälkeen toimitettavassa perintöverotuksessa, perintö- ja lahjaverolain 55 §:ssä tarkoitettua veronhuojennusta laskettaessa, tuli pesään kuuluneiden yritysosakkeiden 

- **3** (d=0.8456, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-suurten-konsernien-vahimmaisverotus-huomioita-ef0cccb9/c11/s11-5/s11-5-2#1`
  > [Source: vero_vero_ohje · in force] [Path: Suurten konsernien vähimmäisverotus - huomioitavat verot > Laskennallisia veroja koskevat siirtymäsäännökset > Varojen siirrot konserniyksiköiden välillä siirtymäkaudella > Poikkeus, jos luovutus on veronalainen] [Title: Poikkeus, jos luovutus on veronalain

- **4** (d=0.8806, vero_ohje / CHAPTER) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-lahjojen-kumulointi-lahjojen-kumulointi-vero-234f3e96/c7#2`
  > [Source: vero_vero_ohje · in force] [Path: Lahjojen kumulointi > Sukupolvenvaihdoshuojennuksen kumulointi] [Title: Sukupolvenvaihdoshuojennuksen kumulointi]  Lahjojen kumulointi — 7 — Sukupolvenvaihdoshuojennuksen kumulointi  Esimerkki Huomio osio alkaa Esimerkki 6: Isä antaa tyttärelleen lahjaksi o

- **5** (d=0.8986, vero_ohje / SECTION) `vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-osakeyhtion-purkautuminen-verotuksessa-osakey-4f0f1dad/c2/s2-3/stuloutettava-omaisuus#0`
  > [Source: vero_vero_ohje · in force] [Path: Osakeyhtiön purkautuminen verotuksessa > Purkautumisen verovaikutukset > Purkautuvan yhtiön varallisuuden arvostaminen käypään arvoon > Tuloutettava omaisuus] [Title: Tuloutettava omaisuus]  Osakeyhtiön purkautuminen verotuksessa — tuloutettava-omaisuus — T
