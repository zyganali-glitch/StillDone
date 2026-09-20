# StillDone — Başlangıç Rehberi

Bu paket **ürün kodu içermez**. Amaç yeni repoyu doğru yönetişim, yarışma kontratı ve Master Plan ile başlatmaktır.

## 1. GitHub deposunu oluştur

GitHub:
- Repository name: `StillDone`
- Owner: `zyganali-glitch`
- Visibility: **Public**
- Initialize with README: **Kapalı**
- Add .gitignore: **None**
- Choose a license: **None**  
  (Bu pakette Apache-2.0 lisansı var.)

Repo adresi hedefi:

`https://github.com/zyganali-glitch/StillDone`

## 2. Yerel klasörü hazırla

Bilgisayarında `StillDone` adlı boş klasör oluştur.

Bu ZIP'in **içeriğini** doğrudan o klasöre çıkar. Son durumda şunlar aynı kökte görünmeli:

- `AGENTS.md`
- `GEMINI.md`
- `README.md`
- `LICENSE`
- `plans/`
- `docs/`

Ekstra `StillDone_Starter_Pack/StillDone_Starter_Pack/...` iç içe klasör oluşturma.

## 3. Antigravity ile aç

StillDone klasörünü Antigravity'de aç.

İlk ajan görevi:

```text
You are bootstrapping a brand-new hackathon repository.

Repository target:
zyganali-glitch/StillDone

Branch:
main

Read AGENTS.md, GEMINI.md, plans/STILLDONE_MASTER_EXECUTION_PLAN.md, docs/HANDOFF.md, and the competition/product contract documents before editing.

Execute exactly:
P-00.01 — Bootstrap canonical StillDone repository from the frozen starter pack

Requirements:
- inspect the current local starter-pack contents;
- inspect the remote first and confirm whether it is empty;
- do not write product/runtime code;
- preserve exact task titles;
- initialize Git only if needed;
- add the canonical origin;
- verify no secrets/local private paths are present;
- verify Apache-2.0 and public-repo competition baseline;
- run focused static/bootstrap integrity checks appropriate for a documentation-only repository;
- commit with the exact-task identifier;
- push main;
- re-check final remote SHA;
- update Master Plan and HANDOFF truth only as needed for P-00.01 closure;
- distinguish NOT_RUN from PASS;
- do not self-award independent QA PASS.

Return the required StillDone closure report from AGENTS.md.
```

## 4. Sonuç raporunu ChatGPT proje sohbetine getir

Ajan raporunu olduğu gibi getir.

Bağımsız QA canonical remote üzerinden yapılacak.

## 5. Kırmızı çizgi

P-00.01 bitmeden ajan:
- ürün kodu yazmayacak;
- AWS servisi seçip mimariyi dondurmayacak;
- Google OAuth entegrasyonu başlatmayacak;
- MCP runtime geliştirmeye başlamayacak.
