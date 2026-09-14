# サードパーティライセンス表記

本プロジェクトの `ng_keywords.txt`（本番運用時に設定するNGワードリスト、`.gitignore`対象で
このリポジトリにはコミットされない）は、以下のオープンソースの日本語NGワード辞書を出典に
含む場合がある。両プロジェクトともMITライセンスで公開されており、著作権表示と許諾表示の
保持が条件となっているため、ここに記載する。

## MosasoM/inappropriate-words-ja

- リポジトリ: https://github.com/MosasoM/inappropriate-words-ja
- ライセンス: MIT License
- Copyright (c) 2020 K Hashimoto

```
MIT License

Copyright (c) 2020 K Hashimoto

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## ClassroomAdventure/wordguard

- リポジトリ: https://github.com/ClassroomAdventure/wordguard
- ライセンス: MIT License
- Copyright (c) 2026 zntrimi
- 備考: `data/ja/` 以下の日本語ワードリストは、上記 MosasoM/inappropriate-words-ja の
  `Sexual.txt` / `Offensive.txt` を土台にオリジナルの追加・分類（`abuse.txt` /
  `ambiguous.txt` / `selfharm.txt` / `allowlist.txt` 等）を加えたもの
  （出典詳細: [ATTRIBUTION.md](https://github.com/ClassroomAdventure/wordguard/blob/main/ATTRIBUTION.md)）。
  英語圏の外部ソース（dsojevic/profanity-list、coffee-and-fun/google-profanity-words、
  zautumnz/profane-words、LDNOOBW）はwordguardの日本語データには使われていないため、
  本プロジェクト（日本語のみ利用）では対象外。

```
MIT License

Copyright (c) 2026 zntrimi

Portions of the word lists in data/ are derived from the following projects.
See ATTRIBUTION.md for a per-file breakdown.

  MosasoM/inappropriate-words-ja      Copyright (c) 2020 K Hashimoto      MIT
  dsojevic/profanity-list             Copyright (c) 2019 Daniel Sojevic   MIT
  coffee-and-fun/google-profanity-words                                   MIT
  zautumnz/profane-words                                                  WTFPL
  LDNOOBW/List-of-Dirty-Naughty-Obscene-and-Otherwise-Bad-Words           CC-BY-4.0

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
