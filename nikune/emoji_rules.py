"""
通常投稿の絵文字ルール（許可リスト方式）の判定

許可する絵文字:
    - 文頭の署名 🐻 を1つ
    - 🥩 または 🍖 を合わせて1つまで
それ以外の絵文字（装飾絵文字、天気・記号系の絵文字、2つ目以降の🐻、2つ目以降の肉系絵文字）は違反として列挙する。

新しい依存を足さずに判定するため、Unicode の絵文字範囲を自前で持つ。
絵文字は「見た目の1文字」（書記素クラスタ）単位で数える:
    - 異体字セレクタ U+FE0F（絵文字表示）は直前の文字と合わせて1つ。U+FE0E（文字表示）が付いたものは絵文字扱いしない
    - 肌の色の修飾子（U+1F3FB〜U+1F3FF）、タグ文字（旗のサブ地域）、囲みキーキャップ U+20E3 は直前の文字と合わせて1つ
    - ZWJ（U+200D）で結合された絵文字列（例: 🐻‍❄️）は全体で1つ。したがって 🐻‍❄️ は署名の 🐻 とは別の絵文字として扱う
    - 地域指示記号（国旗）は2文字で1つ
"""

from typing import List, NamedTuple

SIGNATURE_EMOJI = "🐻"
MEAT_EMOJIS = frozenset({"🥩", "🍖"})
MAX_MEAT_EMOJIS = 1

_VS15 = 0xFE0E  # 文字表示の異体字セレクタ
_VS16 = 0xFE0F  # 絵文字表示の異体字セレクタ
_ZWJ = 0x200D
_KEYCAP = 0x20E3

# 補助多言語面の絵文字ブロック（麻雀牌・トランプ〜記号と絵文字拡張A）。文字単独で絵文字として表示される
_SMP_EMOJI_RANGES = ((0x1F000, 0x1FAFF),)

# 基本多言語面で Unicode の Emoji プロパティを持つ文字（emoji-data.txt より、ASCII の # * 0-9 を除く）
_BMP_EMOJI_RANGES = (
    (0x00A9, 0x00A9),
    (0x00AE, 0x00AE),
    (0x203C, 0x203C),
    (0x2049, 0x2049),
    (0x2122, 0x2122),
    (0x2139, 0x2139),
    (0x2194, 0x2199),
    (0x21A9, 0x21AA),
    (0x231A, 0x231B),
    (0x2328, 0x2328),
    (0x23CF, 0x23CF),
    (0x23E9, 0x23F3),
    (0x23F8, 0x23FA),
    (0x24C2, 0x24C2),
    (0x25AA, 0x25AB),
    (0x25B6, 0x25B6),
    (0x25C0, 0x25C0),
    (0x25FB, 0x25FE),
    (0x2600, 0x2604),
    (0x260E, 0x260E),
    (0x2611, 0x2611),
    (0x2614, 0x2615),
    (0x2618, 0x2618),
    (0x261D, 0x261D),
    (0x2620, 0x2620),
    (0x2622, 0x2623),
    (0x2626, 0x2626),
    (0x262A, 0x262A),
    (0x262E, 0x262F),
    (0x2638, 0x263A),
    (0x2640, 0x2640),
    (0x2642, 0x2642),
    (0x2648, 0x2653),
    (0x265F, 0x2660),
    (0x2663, 0x2663),
    (0x2665, 0x2666),
    (0x2668, 0x2668),
    (0x267B, 0x267B),
    (0x267E, 0x267F),
    (0x2692, 0x2697),
    (0x2699, 0x2699),
    (0x269B, 0x269C),
    (0x26A0, 0x26A1),
    (0x26A7, 0x26A7),
    (0x26AA, 0x26AB),
    (0x26B0, 0x26B1),
    (0x26BD, 0x26BE),
    (0x26C4, 0x26C5),
    (0x26C8, 0x26C8),
    (0x26CE, 0x26CF),
    (0x26D1, 0x26D1),
    (0x26D3, 0x26D4),
    (0x26E9, 0x26EA),
    (0x26F0, 0x26F5),
    (0x26F7, 0x26FA),
    (0x26FD, 0x26FD),
    (0x2702, 0x2702),
    (0x2705, 0x2705),
    (0x2708, 0x270D),
    (0x270F, 0x270F),
    (0x2712, 0x2712),
    (0x2714, 0x2714),
    (0x2716, 0x2716),
    (0x271D, 0x271D),
    (0x2721, 0x2721),
    (0x2728, 0x2728),
    (0x2733, 0x2734),
    (0x2744, 0x2744),
    (0x2747, 0x2747),
    (0x274C, 0x274C),
    (0x274E, 0x274E),
    (0x2753, 0x2755),
    (0x2757, 0x2757),
    (0x2763, 0x2764),
    (0x2795, 0x2797),
    (0x27A1, 0x27A1),
    (0x27B0, 0x27B0),
    (0x27BF, 0x27BF),
    (0x2934, 0x2935),
    (0x2B05, 0x2B07),
    (0x2B1B, 0x2B1C),
    (0x2B50, 0x2B50),
    (0x2B55, 0x2B55),
    (0x3030, 0x3030),
    (0x303D, 0x303D),
    (0x3297, 0x3297),
    (0x3299, 0x3299),
)

# 上のうち、日本語の文章で記号として普通に使われるもの（©®™‼⁉・矢印・四角・三角・〰〽㊗㊙など）。
# これらは U+FE0F が付いて絵文字表示を指定されたときだけ絵文字として数える（誤検知を避けるため）。
# なお ★☆♪→○ などはそもそも Emoji プロパティを持たないため、上の範囲に入っておらず絵文字扱いしない
_TEXT_STYLE_SYMBOLS = frozenset(
    [0x00A9, 0x00AE, 0x203C, 0x2049, 0x2122, 0x2139, 0x24C2, 0x2328, 0x23CF, 0x25B6, 0x25C0, 0x27A1]
    + list(range(0x2194, 0x219A))
    + [0x21A9, 0x21AA, 0x25AA, 0x25AB, 0x25FB, 0x25FC, 0x2934, 0x2935]
    + list(range(0x2B05, 0x2B08))
    + [0x3030, 0x303D, 0x3297, 0x3299]
)

_KEYCAP_BASES = frozenset("0123456789#*")


def _in_ranges(cp: int, ranges: "tuple[tuple[int, int], ...]") -> bool:
    return any(start <= cp <= end for start, end in ranges)


def _is_emoji_base(cp: int) -> bool:
    return _in_ranges(cp, _SMP_EMOJI_RANGES) or _in_ranges(cp, _BMP_EMOJI_RANGES)


def _is_regional_indicator(cp: int) -> bool:
    return 0x1F1E6 <= cp <= 0x1F1FF


def _is_skin_tone(cp: int) -> bool:
    return 0x1F3FB <= cp <= 0x1F3FF


def _is_tag(cp: int) -> bool:
    return 0xE0020 <= cp <= 0xE007F


def _consume_modifiers(text: str, i: int) -> int:
    """位置 i から、直前の絵文字にくっつく修飾（異体字セレクタ・肌の色・タグ・キーキャップ）を読み飛ばす"""
    while i < len(text):
        cp = ord(text[i])
        if cp in (_VS16, _KEYCAP) or _is_skin_tone(cp) or _is_tag(cp):
            i += 1
        else:
            break
    return i


class EmojiOccurrence(NamedTuple):
    """文中の絵文字1つ（見た目の1文字）"""

    position: int  # 文中の開始位置（文字単位）
    emoji: str  # 絵文字を構成する文字列（修飾・ZWJ 結合を含む）


def extract_emojis(text: str) -> List[EmojiOccurrence]:
    """文中の絵文字を、見た目の1文字単位で先頭から順に取り出す"""
    found: List[EmojiOccurrence] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        cp = ord(ch)
        next_cp = ord(text[i + 1]) if i + 1 < n else None

        # キーキャップ（例: 1️⃣）: 数字/#/* + (FE0F) + 20E3
        if ch in _KEYCAP_BASES:
            j = i + 1
            if j < n and ord(text[j]) == _VS16:
                j += 1
            if j < n and ord(text[j]) == _KEYCAP:
                found.append(EmojiOccurrence(i, text[i : j + 1]))
                i = j + 1
                continue
            i += 1
            continue

        # 国旗: 地域指示記号2文字で1つ
        if _is_regional_indicator(cp):
            end = i + 2 if next_cp is not None and _is_regional_indicator(next_cp) else i + 1
            found.append(EmojiOccurrence(i, text[i:end]))
            i = end
            continue

        if not _is_emoji_base(cp) or next_cp == _VS15:
            i += 1
            continue
        if cp in _TEXT_STYLE_SYMBOLS and next_cp != _VS16:
            i += 1
            continue

        start = i
        end = _consume_modifiers(text, i + 1)
        # ZWJ で結合された絵文字列は全体で1つ
        while end + 1 < n and ord(text[end]) == _ZWJ and _is_emoji_base(ord(text[end + 1])):
            end = _consume_modifiers(text, end + 2)
        found.append(EmojiOccurrence(start, text[start:end]))
        i = end
    return found


def _normalize(emoji: str) -> str:
    """🥩️ のように不要な U+FE0F が付いていても同じ絵文字として比較できるようにする"""
    return emoji.replace(chr(_VS16), "")


def find_emoji_rule_violations(text: str) -> List[str]:
    """
    許可リスト方式の絵文字ルールに違反している点を、ログに出せる短い説明で列挙する（違反なしなら空リスト）

    文頭（先頭の空白を除く）の 🐻 1つだけを署名として許可し、🥩/🍖 は合わせて1つまで許可する。
    """
    violations: List[str] = []
    signature_index = len(text) - len(text.lstrip())  # 文頭（先頭の空白を除く）の位置
    extra_signatures: List[str] = []
    meats: List[str] = []
    others: List[str] = []

    for occurrence in extract_emojis(text):
        emoji = _normalize(occurrence.emoji)
        if emoji == SIGNATURE_EMOJI:
            if occurrence.position == signature_index:
                continue  # 文頭の署名
            extra_signatures.append(occurrence.emoji)
        elif emoji in MEAT_EMOJIS:
            meats.append(occurrence.emoji)
        else:
            others.append(occurrence.emoji)

    if others:
        violations.append(f"許可外の絵文字={''.join(others)}")
    if extra_signatures:
        violations.append(f"2つ目以降の{SIGNATURE_EMOJI}={len(extra_signatures)}個")
    if len(meats) > MAX_MEAT_EMOJIS:
        violations.append(f"肉系絵文字が{len(meats)}個（{MAX_MEAT_EMOJIS}個まで）={''.join(meats)}")
    return violations
