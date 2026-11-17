# SVGX-REV1: tajribaga tayyorlik hisoboti

Sana: 2026-11-16. Papka: `D:\13.11.2026\SVG_EXPERIMENT_REV1`. To‘liq protokol: `docs/PROTOCOL_REV1.md` (inglizcha).

Confirmation split’ga **hali tegilmagan**. Har bir tajriba skripti tasdiq ma'lumotlarida ishlashdan oldin
`state/approval_rev1.json` yozuvini tekshiradi. Yozuv bo‘lmasa, skript 4-kod bilan to‘xtaydi.

## 1. Bajarilgan tayyorgarlik

| Qadam | Natija |
|---|---|
| Kodekka `--modes` va `svgx bench` qo‘shildi | build OK, `cargo test` 21/21 |
| R0: sintetik fixture’lar | 30/30 oqim muzlatilgan binar va `expected.json` bilan bir xil |
| R0: pilot | 248/248 fayl; barcha oqimlar va `stats.json` ledger bilan bayt-ma-bayt bir xil |
| T/Z bo‘limlari va cheklangan rejimlar (fixture’lar) | 21 modellangan fixture, nuqson 0 |
| B1 pilotda sinov | 248 fayl, nuqson 0; barcha invariantlar bajarildi |
| paq8px kalibrovkasi (pilot) | -10 daraja tanlandi (peak 7 909 MiB ≤ 8 GiB) |
| zstd lug‘ati (faqat pilot) | 112 640 bayt, SHA-256 `6dbfebad…` |
| B2 smoke (pilot, 8 fayl) | nuqson 0; H ≤ P; barcha oqimlar aylanma tekshiruvdan o‘tdi |
| P-yadro aniqlandi | mantiqiy protsessor 2 (P-sinf); P ≈ 143–158 ms, E ≈ 259 ms |
| B3 tanlamasi | 39 strukturali + 39 o‘lchami juftlangan raw fayl |
| B3 smoke (pilot, 3 fayl) | nuqson 0; biriktirish va HIGH ustuvorlik ishladi |
| pytest | 121/121 (asl 106 + REV1 15) |

## 2. Ochiq yozilishi kerak bo‘lgan qarorlar

1. **paq8px darajasi.** "8 GB" chegarasi kodda kalibrovkadan oldin 2³³ bayt deb belgilangan. -10 darajaning
   peak xotirasi 7 909 MiB, ya'ni 8.29·10⁹ bayt. O‘nlik ma'noda (8·10⁹) o‘qilsa, -9 tanlangan bo‘lardi.
   Bu maqolada ham yoziladi.
2. **cmix chiqarildi.** Hujjatida kamida 32 GB RAM tavsiya qilingan; xostda jami 31.8 GB bor. Tayyor binari ham
   yo‘q. Qaror o‘lchovdan oldin qabul qilingan.
3. **Brotli large-window** 24 o‘rniga 30. Barcha fayllar 16 MiB dan kichik, shuning uchun 24 hech narsa
   qo‘shmaydi.
4. **paq8px** manbadan build qilinmadi. Rasmiy reliz binarisi ishlatildi; uning SHA-256 qiymati GitHub
   digest’i bilan mos keldi. Binari 2026-09-28 da build qilingan, ya'ni ≥ 14 kun eski.
5. **B4 tavsiya qilinmaydi.** Mavjud natijalardan quvvat simulyatsiyasi o‘tkazildi. "Gain > 1%" gipotezasi
   uchun quvvat 120 oilada ham ≤ 0.11. δ = 0 esa konstruksiya bo‘yicha deyarli kafolatlangan, shuning uchun
   ma'nosiz. Yangi ma'lumot yig‘ish faqat yangi gipoteza va alohida ruxsat bilan bo‘ladi.

## 3. Ruxsat so‘raladigan doira

Tartib: **R0 → B1 → B3 → B2 → tahlil**. Ma'lumot: confirmation split (1 076 fayl, 55 oila). Natijalar maqolada
"previously analysed data" deb belgilanadi.

| Bosqich | Nima qilinadi | Taxminiy vaqt |
|---|---|---|
| R0 | Yangi build 1 076 faylda muzlatilgan natijani aynan takrorlashi | ≈ 3 daqiqa |
| B1 | D0/M01/M010 rejimlari, T va Z variantlari; R1 estimandi | ≈ 10 daqiqa |
| B3 | 78 faylda jarayon ichidagi vaqt o‘lchovi; τ_dec estimandi | ≈ 1–1.5 soat |
| B2 | paq8px -10, gibrid H, zstd-dict va Brotli variantlari; Gain_H estimandi | ≈ 4–5 soat |
| Tahlil | 50 000 oilaviy bootstrap, Bonferroni k = 3, BCa | bir necha daqiqa |

B3 o‘lchovi davomida Windows quvvat rejimi vaqtincha "High performance" holatiga o‘tkaziladi va oxirida avvalgi
holatiga qaytariladi. B2 vaqtida xotira ~24 GB gacha band bo‘ladi, ya'ni 3 ta paq8px jarayoni. O‘lchov paytida
kompyuterda boshqa og‘ir ish qilmaslik tavsiya etiladi.

## 4. Ishga tushirish (ruxsatdan keyin)

```
python rev1\approve.py approve --scope R0,B1,B3,B2,analysis --note "<foydalanuvchi javobi>"
run_rev1.cmd
```

Biror bosqich xato bersa, ish shu joyda to‘xtaydi; batafsil ma'lumot `results_rev1\run_all.log` faylida bo‘ladi.
Qayta ishga tushirilganda tugallangan fayllar qayta hisoblanmaydi.
