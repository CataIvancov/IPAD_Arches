# IPAD Arches

**[English](#english) | [Bahasa Indonesia](#bahasa-indonesia)**

---

## English

**Indonesian Prehistoric Archaeology Database** — a public heritage inventory of prehistoric archaeological sites in Indonesia.

This is the Arches **project** that runs IPAD. It is not a fork of [Arches core](https://github.com/archesproject/arches), and it is not the default Arches sample app.

**Live site:** [arches.ipadarkeo.id](https://arches.ipadarkeo.id/)

Search and map published sites without signing in. English and Indonesian (`id`) are both available in the UI.

### What this repo is

An Arches 8.1 project (`ipad`) maintained by [Cata Ivancov](https://github.com/CataIvancov) for Nusantara Heritage.

| This repo | Not this repo |
| --- | --- |
| IPAD site: graphs, templates, importers, Indonesian UI, public search | Arches engine source |
| Live code from the production project | `archesproject/arches` |
| Custom Place / Site (Archaeology) model and IPAD data workflows | Generic “new Arches project” starter |

Upstream Arches is a **dependency** (`arches>=8.1.3,<8.2.0`, frontend pin `stable/8.1.4`). Core patches and locale PRs belong in the engine fork, not here.

### Related repositories

- **[IPAD_ArkeOpen](https://github.com/CataIvancov/IPAD_ArkeOpen)** — the ArkeOpen platform for the same database (different stack).
- **[arches_ipad](https://github.com/CataIvancov/arches_ipad)** — fork of Arches core, used for upstream contributions (for example Indonesian locale [PR #12905](https://github.com/archesproject/arches/pull/12905)).
- **[Arches](https://www.archesproject.org/)** — the open-source GIS this project is built on.

Site CSVs and bibliography matching still live with the ArkeOpen data tree; the scripts in this repo import that data into Arches.

### What is IPAD-specific

- **Place / Site (Archaeology)** resource model (`ipad_place_site_archeology`), with island (*Pulau*) assignment from Indonesian geography.
- **Public published records:** guests can view published resources; unpublished graphs stay private. Arches System Settings is never public.
- **Homepage, search, map, and policy pages** written for IPAD (not the stock Arches splash), including privacy, terms, cookies, and accessibility.
- **Basemaps:** OSM, satellite, and OpenTopoMap (no Mapbox-required default map).
- **Indonesian UI:** project strings in `ipad/locale/`; vendored Arches-core Indonesian in `arches_locale/` so `pip` upgrades do not wipe Weblate translations.
- **Data scripts** (dry-run by default; pass `--apply` to write):
  - `import_ipad_sites_to_arches.py` — regional site CSVs → Place resources
  - `import_ipad_external_media.py` — bibliography PDFs as external Information Resources
  - `populate_site_islands.py` — Geography Island / Pulau on Place records
  - `fix_sangiran_arches_geometry.py` — Sangiran coordinates
  - `convert_schemes_to_controlled_lists.py` — RDM schemes → controlled lists

IPAD is a research database. It is not a substitute for official archaeological permits.

### Layout

```
ipad/                 Django project (settings, URLs, templates, views)
arches_locale/        Vendored Arches-core Indonesian gettext catalog
webpack/              Frontend build
import_*.py           One-off IPAD data loaders
```

Secrets stay out of git (`ipad/settings_local.py`, database, Elasticsearch). Clone this repo to inspect the project; it will not boot as a live site without that local config and the usual Arches services (PostgreSQL/PostGIS, Elasticsearch, a Python 3.11+ env).

### Contact

Questions about IPAD: **cata@nusantaraheritage.org**

License: GNU Affero General Public License v3.0 (same family as Arches).

---

## Bahasa Indonesia

**Indonesian Prehistoric Archaeology Database (Basis Data Arkeologi Prasejarah Indonesia)** — inventaris warisan budaya publik untuk situs arkeologi prasejarah di Indonesia.

Ini adalah **proyek** Arches yang menjalankan IPAD. Bukan fork [inti Arches](https://github.com/archesproject/arches), dan bukan aplikasi contoh bawaan Arches.

**Situs langsung:** [arches.ipadarkeo.id](https://arches.ipadarkeo.id/)

Pengunjung dapat mencari dan memetakan situs yang sudah diterbitkan tanpa masuk. Antarmuka tersedia dalam bahasa Inggris dan Indonesia (`id`).

### Apa isi repositori ini

Proyek Arches 8.1 (`ipad`) yang dikelola [Cata Ivancov](https://github.com/CataIvancov) untuk Nusantara Heritage.

| Repositori ini | Bukan repositori ini |
| --- | --- |
| Situs IPAD: graf, templat, pengimpor, UI bahasa Indonesia, pencarian publik | Kode sumber mesin Arches |
| Kode dari proyek produksi | `archesproject/arches` |
| Model Place / Site (Archaeology) dan alur data IPAD | Starter “proyek Arches baru” generik |

Arches hulu adalah **dependensi** (`arches>=8.1.3,<8.2.0`, pin frontend `stable/8.1.4`). Perbaikan inti dan PR locale masuk ke fork mesin, bukan ke sini.

### Repositori terkait

- **[IPAD_ArkeOpen](https://github.com/CataIvancov/IPAD_ArkeOpen)** — platform ArkeOpen untuk basis data yang sama (tumpukan berbeda).
- **[arches_ipad](https://github.com/CataIvancov/arches_ipad)** — fork inti Arches, untuk kontribusi ke hulu (misalnya locale Indonesia [PR #12905](https://github.com/archesproject/arches/pull/12905)).
- **[Arches](https://www.archesproject.org/)** — GIS sumber terbuka yang menjadi dasar proyek ini.

Berkas CSV situs dan pencocokan bibliografi tetap di pohon data ArkeOpen; skrip di repositori ini mengimpor data itu ke Arches.

### Yang khas IPAD

- **Model sumber daya Place / Site (Archaeology)** (`ipad_place_site_archeology`), dengan penugasan pulau (*Pulau*) dari geografi Indonesia.
- **Catatan terbitan yang publik:** tamu dapat melihat sumber daya yang sudah diterbitkan; graf yang belum diterbitkan tetap privat. Pengaturan Sistem Arches tidak pernah publik.
- **Beranda, pencarian, peta, dan halaman kebijakan** ditulis untuk IPAD (bukan splash Arches bawaan), termasuk privasi, ketentuan, cookie, dan aksesibilitas.
- **Peta dasar:** OSM, satelit, dan OpenTopoMap (tanpa peta bawaan yang wajib Mapbox).
- **UI bahasa Indonesia:** string proyek di `ipad/locale/`; katalog Indonesia inti Arches di `arches_locale/` agar peningkatan `pip` tidak menghapus terjemahan Weblate.
- **Skrip data** (uji-coba secara bawaan; tambahkan `--apply` untuk menulis):
  - `import_ipad_sites_to_arches.py` — CSV situs regional → sumber daya Place
  - `import_ipad_external_media.py` — PDF bibliografi sebagai Information Resource eksternal
  - `populate_site_islands.py` — Pulau pada catatan Place
  - `fix_sangiran_arches_geometry.py` — koordinat Sangiran
  - `convert_schemes_to_controlled_lists.py` — skema RDM → daftar terkendali

IPAD adalah basis data penelitian. Bukan pengganti izin resmi arkeologi.

### Tata letak

```
ipad/                 Proyek Django (pengaturan, URL, templat, tampilan)
arches_locale/        Katalog gettext Indonesia inti Arches (tersimpan di sini)
webpack/              Bangun frontend
import_*.py           Pengimpor data IPAD sekali pakai
```

Rahasia tidak masuk git (`ipad/settings_local.py`, basis data, Elasticsearch). Klon repositori ini untuk meninjau proyek; situs tidak akan jalan tanpa konfigurasi lokal itu dan layanan Arches biasa (PostgreSQL/PostGIS, Elasticsearch, lingkungan Python 3.11+).

### Kontak

Pertanyaan tentang IPAD: **cata@nusantaraheritage.org**

Lisensi: GNU Affero General Public License v3.0 (keluarga lisensi yang sama dengan Arches).
