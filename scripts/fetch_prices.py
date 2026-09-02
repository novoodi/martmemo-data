"""
한국소비자원 참가격 GW 오픈API → 정적 JSON 게시용 스크립트 (표준 라이브러리만 사용).

출력(모두 data/ 아래):
  index.json            판매점·상품 사전 + 보유 조사일 목록 + 최신 조사일
  prices/YYYYMMDD.json  조사일 하나의 전체 가격 [goodId, entpId, priceWon] (약 3MB)
  trend.json            상품별·조사일별·업태별 중앙값 (앱 추이/배지용, 작음)

환경변수:
  KCA_SERVICE_KEY  data.go.kr 일반 인증키 (Encoding/Decoding 어느 쪽이든 됨)
  MAX_NEW_DAYS     이번 실행에서 새로 받을 조사일 수 (기본 2, 일일 한도 2,000 고려)
  SCAN_DAYS        조사일 탐색 범위(일, 기본 120) — 금요일만 확인

인증키는 절대 로그·파일에 출력하지 않는다.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import statistics
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = "https://apis.data.go.kr/B551919/ProductPriceInfoService"
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PRICES = DATA / "prices"

STORE_TYPES = {"LM": "대형마트", "SM": "SSM", "DP": "백화점", "CS": "편의점", "TM": "전통시장"}


def service_key() -> str:
    key = os.environ.get("KCA_SERVICE_KEY", "").strip()
    if not key:
        sys.exit("KCA_SERVICE_KEY 환경변수가 없습니다")
    # 포털의 Encoding 키(%2F 포함)는 그대로, Decoding 키(/ + = 포함)는 인코딩해서 사용
    return key if "%" in key else urllib.parse.quote(key, safe="")


KEY = service_key()


def call(op: str, **params: str) -> ET.Element:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{BASE}/{op}?serviceKey={KEY}" + (f"&{query}" if query else "")
    last_err: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                body = resp.read()
            root = ET.fromstring(body)
            code = root.findtext("resultCode")
            if root.tag == "OpenAPI_ServiceResponse":  # 게이트웨이 오류(한도 초과·키 오류 등)
                msg = root.findtext(".//returnAuthMsg") or root.findtext(".//errMsg") or "?"
                raise RuntimeError(f"gateway error: {msg}")
            if code not in (None, "00"):
                raise RuntimeError(f"{op} resultCode={code} {root.findtext('resultMsg')}")
            return root
        except Exception as e:  # noqa: BLE001 — 재시도 후 마지막 오류를 올린다
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    # URL(키 포함)은 절대 출력하지 않는다
    raise RuntimeError(f"{op} {params} 실패: {last_err}")


def text(el: ET.Element, tag: str) -> str | None:
    v = el.findtext(tag)
    return v.strip() if v else None


def num(el: ET.Element, tag: str) -> float | None:
    v = text(el, tag)
    try:
        return float(v) if v is not None else None
    except ValueError:
        return None


def fetch_stores() -> list[dict]:
    root = call("getStoreInfoSvc.do")
    out = []
    for e in root.iter():
        if not e.tag.endswith("entpInfoVO"):
            continue
        addr = text(e, "roadAddrBasic") or text(e, "plmkAddrBasic") or ""
        out.append({
            "id": int(text(e, "entpId")),
            "name": text(e, "entpName"),
            "type": text(e, "entpTypeCode"),
            "area": text(e, "entpAreaCode"),
            "areaDetail": text(e, "areaDetailCode"),
            "addr": addr,
            "lat": num(e, "xMapCoord"),
            "lng": num(e, "yMapCoord"),
        })
    out.sort(key=lambda s: s["id"])
    return out


def fetch_products() -> list[dict]:
    root = call("getProductInfoSvc.do")
    out = []
    for e in root.iter("item"):
        out.append({
            "id": int(text(e, "goodId")),
            "name": text(e, "goodName"),
            "unit": text(e, "goodUnitDivCode"),
            "base": num(e, "goodBaseCnt"),
            "total": num(e, "goodTotalCnt"),
            "totalUnit": text(e, "goodTotalDivCode"),
            "cls": text(e, "goodSmlclsCode"),
            "detail": text(e, "detailMean"),
        })
    out.sort(key=lambda p: p["id"])
    return out


def price_rows(root: ET.Element) -> list[list[int]]:
    rows = []
    for e in root.iter():
        if e.tag.endswith("goodPriceVO"):
            rows.append([int(text(e, "goodId")), int(text(e, "entpId")), int(float(text(e, "goodPrice")))])
    return rows


def has_data(day: str, probe_good_id: int) -> bool:
    return bool(price_rows(call("getProductPriceInfoSvc", goodInspectDay=day, goodId=str(probe_good_id))))


def fridays_back(days: int) -> list[str]:
    today = dt.date.today()
    out = []
    for i in range(days):
        d = today - dt.timedelta(days=i)
        if d.weekday() == 4:
            out.append(d.strftime("%Y%m%d"))
    return out  # 최신순


def fetch_day(day: str, product_ids: list[int]) -> list[list[int]]:
    rows: list[list[int]] = []
    for i, gid in enumerate(product_ids, 1):
        rows.extend(price_rows(call("getProductPriceInfoSvc", goodInspectDay=day, goodId=str(gid))))
        if i % 100 == 0:
            print(f"  {day}: {i}/{len(product_ids)} 상품, {len(rows)}행")
        time.sleep(0.05)
    rows.sort()
    return rows


def build_trend(days: list[str], stores: list[dict]) -> dict:
    """상품별 × 조사일별 × 업태별 중앙값. 앱 스파크라인·배지는 이것만 있으면 된다."""
    store_type = {s["id"]: s["type"] for s in stores}
    trend: dict[int, dict[str, dict[str, int]]] = {}
    for day in days:
        rows = json.loads((PRICES / f"{day}.json").read_text(encoding="utf-8"))["rows"]
        by_good: dict[int, dict[str, list[int]]] = {}
        for gid, eid, price in rows:
            t = store_type.get(eid, "?")
            by_good.setdefault(gid, {}).setdefault(t, []).append(price)
            by_good[gid].setdefault("ALL", []).append(price)
        for gid, by_type in by_good.items():
            trend.setdefault(gid, {})[day] = {t: int(statistics.median(v)) for t, v in by_type.items()}
    return {"days": days, "types": STORE_TYPES, "products": {str(g): d for g, d in sorted(trend.items())}}


def main() -> None:
    max_new = int(os.environ.get("MAX_NEW_DAYS", "2"))
    scan_days = int(os.environ.get("SCAN_DAYS", "120"))
    PRICES.mkdir(parents=True, exist_ok=True)

    print("판매점·상품 사전 받는 중")
    stores = fetch_stores()
    products = fetch_products()
    print(f"  판매점 {len(stores)}, 상품 {len(products)}")

    have = sorted(p.stem for p in PRICES.glob("*.json"))
    probe = 1000 if any(p["id"] == 1000 for p in products) else products[0]["id"]
    print(f"조사일 탐색(최근 {scan_days}일 금요일), 보유 {len(have)}일")
    new_days = []
    for day in fridays_back(scan_days):
        if day in have:
            continue
        if has_data(day, probe):
            new_days.append(day)
        time.sleep(0.05)
    new_days = new_days[:max_new]  # 최신 것부터, 한도 안에서
    print(f"  새 조사일 {new_days} (이번 실행 최대 {max_new})")

    ids = [p["id"] for p in products]
    for day in new_days:
        print(f"{day} 가격 받는 중 ({len(ids)}회 호출)")
        rows = fetch_day(day, ids)
        (PRICES / f"{day}.json").write_text(
            json.dumps({"day": day, "rows": rows}, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        print(f"  저장: {len(rows)}행")

    days = sorted(p.stem for p in PRICES.glob("*.json"))
    index = {
        "generatedAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "한국소비자원 참가격(공공데이터포털 한국소비자원_생필품 가격 정보_GW)",
        "latestDay": days[-1] if days else None,
        "days": days,
        "storeTypes": STORE_TYPES,
        "stores": stores,
        "products": products,
    }
    (DATA / "index.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if days:
        (DATA / "trend.json").write_text(
            json.dumps(build_trend(days, stores), ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
    print(f"완료: 조사일 {len(days)}개, 최신 {index['latestDay']}")


if __name__ == "__main__":
    main()
