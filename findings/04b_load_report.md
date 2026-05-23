# 04b Graph load report

## Row counts

- nodes (db / file): **1,967,776** / 1,967,776
- edges (db / file): **2,180,769** / 2,180,769
- roots (parent_id IS NULL): 63,661
- dangling edges (target_id IS NULL): 0
- nodes with non-empty degree: 1,967,769

## Edge types

- `parent_of`: 1,904,115
- `defines`: 234,570
- `applies`: 18,259
- `interprets`: 16,613
- `cites`: 7,164
- `amends`: 24
- `repeals`: 24

## Smoke tests

- Section finlex/laki/finlex-laki-laki-oikeudenkaynnista-rikosasioissa-annetun-lain-1-luvun-14-n-muutt-25c86f46/c1/s14 has 2 parent_of children (expect > 0 for a non-leaf section)
- Resolved interprets edges (vero → finlex etc.): 16,613

## Top inbound-degree hubs (per edge type)


### `parent_of` (inbound)

- `finlex/asetus/finlex-asetus-aikuislukioasetus-html-497931cb/c1` ← 1
- `finlex/asetus/finlex-asetus-aikuislukioasetus-html-497931cb/c1/s1` ← 1
- `finlex/asetus/finlex-asetus-aikuislukioasetus-html-497931cb/c1/s1/m1` ← 1
- `finlex/asetus/finlex-asetus-aikuislukioasetus-html-497931cb/c1/s1/m2` ← 1
- `finlex/asetus/finlex-asetus-aikuislukioasetus-html-497931cb/c1/s2` ← 1

### `defines` (inbound)

- `finlex/laki_skk/finlex-laki-saadoskokoelma-laki-suurten-konsernien-vahimmaisverosta-html-3fff205a/c3/s8/i8` ← 36
- `finlex/laki_skk/finlex-laki-saadoskokoelma-laki-suurten-konsernien-vahimmaisverosta-html-3fff205a/c3/s7/m3` ← 35
- `finlex/laki_skk/finlex-laki-saadoskokoelma-laki-raportoivien-finanssilaitosten-tiedonantovelvoll-30ad7786/c2/s76/m2` ← 34
- `finlex/laki_skk/finlex-laki-saadoskokoelma-laki-raportoivien-finanssilaitosten-tiedonantovelvoll-30ad7786/c2/s77/m1` ← 34
- `finlex/laki_skk/finlex-laki-saadoskokoelma-laki-raportoivien-finanssilaitosten-tiedonantovelvoll-30ad7786/c2/s93/m1` ← 34

### `applies` (inbound)

- `finlex/laki/finlex-laki-tuloverolaki-html-9e9b64a4` ← 3,795
- `finlex/laki/finlex-laki-arvonlisaverolaki-html-ba5d8e0e` ← 2,167
- `finlex/laki/finlex-laki-hallintolaki-html-996f8329` ← 1,389
- `finlex/laki/finlex-laki-laki-elinkeinotulon-verottamisesta-html-365a54e1` ← 601
- `finlex/laki/finlex-laki-varainsiirtoverolaki-html-8ff09a61` ← 393

### `interprets` (inbound)

- `finlex/laki/finlex-laki-tuloverolaki-html-9e9b64a4` ← 6,934
- `finlex/laki/finlex-laki-arvonlisaverolaki-html-ba5d8e0e` ← 3,284
- `finlex/laki/finlex-laki-laki-elinkeinotulon-verottamisesta-html-365a54e1` ← 2,364
- `finlex/laki/finlex-laki-laki-verotusmenettelysta-html-92ea98e2` ← 1,057
- `finlex/laki/finlex-laki-laki-oma-aloitteisten-verojen-verotusmenettelysta-html-3957aa52` ← 225

### `cites` (inbound)

- `finlex/laki/finlex-laki-tuloverolaki-html-9e9b64a4` ← 446
- `finlex/laki/finlex-laki-hallintolaki-html-996f8329` ← 361
- `finlex/laki/finlex-laki-ennakkoperintalaki-1-html-c4e849e0` ← 312
- `finlex/laki/finlex-laki-arvonlisaverolaki-html-ba5d8e0e` ← 229
- `finlex/laki/finlex-laki-laki-opintotukilain-65-1994-nojalla-vuodelta-1999-maksetun-opintorah-49c0f6c4` ← 84

## Verdict

**PASS** — all invariants hold.