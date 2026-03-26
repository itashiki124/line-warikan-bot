"""割り勘計算のユニットテスト"""
import pytest
from app.warikan import (
    calculate_warikan,
    calculate_transfers,
    parse_warikan_message,
    parse_record_message,
    parse_member_message,
    GroupSession,
    Transfer,
)


class TestCalculateWarikan:
    def test_even_split(self):
        r = calculate_warikan(3000, 3)
        assert r.base_amount == 1000
        assert r.remainder == 0

    def test_odd_split(self):
        r = calculate_warikan(3100, 3)
        assert r.base_amount == 1033
        assert r.remainder == 1  # 1人だけ1034円

    def test_large_remainder(self):
        r = calculate_warikan(1001, 3)
        assert r.base_amount == 333
        assert r.remainder == 2  # 2人が334円

    def test_single_person(self):
        r = calculate_warikan(500, 1)
        assert r.base_amount == 500
        assert r.remainder == 0

    def test_zero_amount(self):
        r = calculate_warikan(0, 3)
        assert r.base_amount == 0

    def test_invalid_people(self):
        with pytest.raises(ValueError):
            calculate_warikan(1000, 0)


class TestParseWarikanMessage:
    def test_basic(self):
        assert parse_warikan_message("3000円 3人") == (3000, 3)

    def test_comma_in_amount(self):
        assert parse_warikan_message("10,000円 4人") == (10000, 4)

    def test_no_yen_mark(self):
        assert parse_warikan_message("5000 5人") == (5000, 5)

    def test_with_fullwidth_yen(self):
        assert parse_warikan_message("￥2000 2人") == (2000, 2)

    def test_unrelated_text(self):
        assert parse_warikan_message("こんにちは") is None

    # 柔軟なパースのテスト
    def test_people_first(self):
        """「3人で5000円」のように人数が先の場合"""
        assert parse_warikan_message("3人で5000円") == (5000, 3)

    def test_with_description_prefix(self):
        """「飲み会5000円4人」のように説明付き"""
        assert parse_warikan_message("飲み会5000円4人") == (5000, 4)

    def test_with_warikan_keyword(self):
        """「5000円を3人で割り勘」"""
        assert parse_warikan_message("5000円を3人で割り勘") == (5000, 3)

    def test_with_watte(self):
        """「5000円を3人で割って」"""
        assert parse_warikan_message("5000円を3人で割って") == (5000, 3)

    def test_casual_with_de(self):
        """「ランチ代3000円、3人で」"""
        assert parse_warikan_message("ランチ代3000円、3人で") == (3000, 3)

    def test_reverse_order_with_description(self):
        """「4人で10000円のディナー」"""
        assert parse_warikan_message("4人で10000円のディナー") == (10000, 4)

    def test_yesterday_lunch(self):
        """「昨日のランチ3000円を3人で」"""
        assert parse_warikan_message("昨日のランチ3000円を3人で") == (3000, 3)


class TestParseRecordMessage:
    def test_basic(self):
        result = parse_record_message("記録 1500円 ランチ")
        assert result == (1500, "ランチ", None)

    def test_no_label(self):
        result = parse_record_message("記録 2000円")
        assert result is not None
        assert result[0] == 2000

    def test_english(self):
        result = parse_record_message("add 3000円 dinner")
        assert result == (3000, "dinner", None)

    def test_with_payer(self):
        """「記録 田中 3000円 ランチ」で支払者付き"""
        result = parse_record_message("記録 田中 3000円 ランチ")
        assert result == (3000, "ランチ", "田中")

    def test_with_payer_no_label(self):
        """「記録 田中 2000円」支払者あり、ラベルなし"""
        result = parse_record_message("記録 田中 2000円")
        assert result is not None
        assert result[0] == 2000
        assert result[2] == "田中"

    def test_without_payer(self):
        """「記録 1500円 ランチ」支払者なし"""
        result = parse_record_message("記録 1500円 ランチ")
        assert result == (1500, "ランチ", None)


class TestParseMemberMessage:
    def test_basic(self):
        result = parse_member_message("メンバー 田中 山田 鈴木")
        assert result == ["田中", "山田", "鈴木"]

    def test_comma_separated(self):
        result = parse_member_message("メンバー 田中,山田,鈴木")
        assert result == ["田中", "山田", "鈴木"]

    def test_japanese_comma(self):
        result = parse_member_message("メンバー 田中、山田、鈴木")
        assert result == ["田中", "山田", "鈴木"]

    def test_hiragana(self):
        result = parse_member_message("めんばー たなか やまだ")
        assert result == ["たなか", "やまだ"]

    def test_unrelated(self):
        assert parse_member_message("こんにちは") is None


class TestCalculateTransfers:
    def test_simple_two_people(self):
        """田中が全額払い → 山田が田中に半額払う"""
        session = GroupSession()
        session.set_members(["田中", "山田"])
        session.add_payment(2000, "ランチ", "田中")

        transfers = calculate_transfers(session, 2)
        assert len(transfers) == 1
        assert transfers[0].from_person == "山田"
        assert transfers[0].to_person == "田中"
        assert transfers[0].amount == 1000

    def test_three_people_one_payer(self):
        """田中が3000円全額 → 山田・鈴木が各1000円を田中に"""
        session = GroupSession()
        session.set_members(["田中", "山田", "鈴木"])
        session.add_payment(3000, "ディナー", "田中")

        transfers = calculate_transfers(session, 3)
        assert len(transfers) == 2
        total_to_tanaka = sum(t.amount for t in transfers if t.to_person == "田中")
        assert total_to_tanaka == 2000

    def test_multiple_payers(self):
        """田中3000円、山田2000円 → 精算で差額調整"""
        session = GroupSession()
        session.set_members(["田中", "山田", "鈴木"])
        session.add_payment(3000, "ランチ", "田中")
        session.add_payment(2000, "コーヒー", "山田")

        # 合計5000、1人あたり1666円(端数1円は田中)
        # 田中: 3000 - 1667 = +1333
        # 山田: 2000 - 1666 = +334
        # 鈴木: 0 - 1666 = -1666
        # → 鈴木が田中に1333、山田に334 (合計=1667...端数含め1666)
        transfers = calculate_transfers(session, 3)
        assert len(transfers) >= 1
        # 鈴木が支払う合計額を確認
        suzuki_pays = sum(t.amount for t in transfers if t.from_person == "鈴木")
        # 鈴木の負担は 5000//3 = 1666円 (端数は田中に加算)
        assert suzuki_pays == 1666

    def test_no_payer_info(self):
        """支払者情報がない時は空リスト"""
        session = GroupSession()
        session.set_members(["田中", "山田"])
        session.add_payment(2000, "ランチ")

        transfers = calculate_transfers(session, 2)
        assert transfers == []

    def test_no_members(self):
        """メンバー未設定時は空リスト"""
        session = GroupSession()
        session.add_payment(2000, "ランチ", "田中")

        transfers = calculate_transfers(session, 2)
        assert transfers == []

    def test_already_even(self):
        """全員均等に払っていれば送金不要"""
        session = GroupSession()
        session.set_members(["田中", "山田"])
        session.add_payment(1000, "ランチ", "田中")
        session.add_payment(1000, "コーヒー", "山田")

        transfers = calculate_transfers(session, 2)
        assert transfers == []
