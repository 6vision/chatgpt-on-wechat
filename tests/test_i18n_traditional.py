# encoding:utf-8
"""The Simplified -> Traditional tables have to pair up one to one.

``to_traditional()`` reads the two tables positionally, pairing them with
``zip()``. That makes the pairings fragile in a way a single lookup would not
be: a character missing from one table shifts every pairing after it onto the
wrong output, and the tail left without a partner is dropped and stays
Simplified.

The tables had drifted exactly that way. ``_TRADITIONAL`` ended with the
``_PHRASE_MAP`` terms appended to it, which does nothing for the character map
(it only ever looks up ``_SIMPLIFIED`` keys) but pushed the last 37 real
pairings onto those words. So 37 characters were converted to an unrelated
character and the final 57 were not converted at all -- 94 of 450, a fifth of
the table.

OpenCC is an optional dependency (``requirements-optional.txt``), so on a
default install this table is the whole conversion path for ``zh-Hant``.
"""

from common.i18n import _SIMPLIFIED, _TRADITIONAL, to_traditional

# 37 characters that used to be paired with the appended phrase-map terms.
_MISPAIRED = "赋赖赘轩转轮软轻载较辑输边达过运还这进远违连迟适选递逻遥邮邻采释里鉴针钉钟"
_MISPAIRED_TRADITIONAL = "賦賴贅軒轉輪軟輕載較輯輸邊達過運還這進遠違連遲適選遞邏遙郵鄰採釋裡鑑針釘鐘"

# 57 characters that had no partner left once the tables ran out of each other.
_UNMAPPED = "钥钮钱铁链销锁错锤键镜长闭问闲间闺闻闽阅队阳际陆陕险随隐难静韩页项顺须顾预领频题额风飞饭饰馆馈馏马驻驿验骤鱼鸡麦齐"
_UNMAPPED_TRADITIONAL = "鑰鈕錢鐵鏈銷鎖錯錘鍵鏡長閉問閒間閨聞閩閱隊陽際陸陝險隨隱難靜韓頁項順須顧預領頻題額風飛飯飾館饋餾馬駐驛驗驟魚雞麥齊"


def test_tables_pair_one_to_one():
    assert len(_SIMPLIFIED) == len(_TRADITIONAL), (
        f"{len(_SIMPLIFIED)} simplified characters against "
        f"{len(_TRADITIONAL)} traditional ones; zip() pairs them by position, "
        "so the extra ones are silently dropped"
    )


def test_no_entry_is_paired_with_itself():
    """A self-pairing means the two tables have drifted out of step."""
    unchanged = [s for s, t in zip(_SIMPLIFIED, _TRADITIONAL) if s == t]
    assert not unchanged, f"paired with themselves: {''.join(unchanged)}"


def test_converts_characters_that_used_to_be_mispaired():
    assert to_traditional(_MISPAIRED) == _MISPAIRED_TRADITIONAL


def test_converts_characters_that_used_to_have_no_partner():
    assert to_traditional(_UNMAPPED) == _UNMAPPED_TRADITIONAL


def test_converts_a_sentence_into_a_single_script():
    assert to_traditional("问题很长，需要钥匙") == "問題很長，需要鑰匙"
