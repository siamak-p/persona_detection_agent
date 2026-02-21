import logging
from collections import defaultdict
import asyncio
from typing import List, Dict, Any
import holidays
from datetime import timedelta
from zoneinfo import ZoneInfo
from dateutil import parser
import jdatetime
from db.postgres_relationship_cluster_personas import RelationshipClusterPersonas
from db.postgres_dyadic_overrides import DyadicOverrides
from db.passive_storage import PassiveStorage

logger = logging.getLogger(__name__)


class PassiveStoragesHandler:
    def __init__(self, relationhip_cluster: RelationshipClusterPersonas, dyadic: DyadicOverrides, passive_storage: PassiveStorage) -> None:
        self._relationship = relationhip_cluster
        self._dyadic = dyadic
        self._passive = passive_storage


async def build_conversation_turns_grouped(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    logger.debug("Building conversation turns from %d rows", len(rows))
    conv_dict = defaultdict(list)
    for r in rows:
        conv_dict[r["conversation_id"]].append(r)

    results = []

    for conv_id, messages in conv_dict.items():
        messages.sort(key=lambda x: x["timestamp_iso"])

        turns = []
        turn_index = 1

        for msg in messages:
            turns.append({
                "index": turn_index,
                "speaker_id": msg["user_id"],
                "text": msg["message"],
                "timestamp": msg["timestamp_iso"]
            })
            turn_index += 1

        results.append({
            "conversation_id": conv_id,
            "turns": turns
        })

    return results


async def dramatize_conversations(rows: List[Dict]) -> Dict[str, str]:
    logger.debug("Dramatizing %d conversation rows", len(rows))
    sorted_rows = sorted(rows, key=lambda x: x.get('timestamp_iso', ''))

    conversations = defaultdict(list)
    for row in sorted_rows:
        conv_id = row.get('conversation_id', 'unknown')
        conversations[conv_id].append(row)

    formatted_logs = {}
    
    for conv_id, messages in conversations.items():
        log_lines = ["Conversation Log:"]
        
        for msg in messages:
            user = msg.get('user_id', 'Unknown')
            text = msg.get('message', '').strip()
            
            log_lines.append(f"{user}: {text}")
        
        formatted_logs[conv_id] = "\n ".join(log_lines)
        
        await asyncio.sleep(0) 

    return formatted_logs


async def transform_to_conversation_structure(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    logger.debug("Transforming %d rows to conversation structure", len(rows))
    
    grouped_data = defaultdict(list)
    for row in rows:
        conv_id = row.get("conversation_id")
        if conv_id:
            grouped_data[conv_id].append(row)

    conversations_list = []

    for conv_id, messages in grouped_data.items():
        messages.sort(key=lambda x: x.get("timestamp_iso", ""))

        participants = list(set(msg.get("user_id") for msg in messages if msg.get("user_id")))
        user_a = participants[0] if len(participants) > 0 else None
        user_b = participants[1] if len(participants) > 1 else None

        turns = []
        
        short_msg_buffer = []

        def flush_buffer():
            nonlocal turns, short_msg_buffer
            if not short_msg_buffer:
                return

            if len(short_msg_buffer) >= 5:
                merged_text = " ".join([m.get("message", "") or "" for m in short_msg_buffer])
                turns.append({
                    "speaker": short_msg_buffer[0].get("user_id"),
                    "text": merged_text
                })
            else:
                for m in short_msg_buffer:
                    turns.append({
                        "speaker": m.get("user_id"),
                        "text": m.get("message", "") or ""
                    })
            
            short_msg_buffer = []

        for msg in messages:
            user_id = msg.get("user_id")
            text = msg.get("message", "") or ""
            word_count = len(text.split())
            is_short = word_count < 3
            
            
            should_flush = False
            if short_msg_buffer:
                last_user = short_msg_buffer[0].get("user_id")
                if last_user != user_id:
                    should_flush = True
                elif not is_short:
                    should_flush = True
            
            if should_flush:
                flush_buffer()

            if is_short:
                short_msg_buffer.append(msg)
            else:
                turns.append({
                    "speaker": user_id,
                    "text": text
                })
        
        flush_buffer()

        conversation_obj = {
            "conversation_id": conv_id,
            "user_a_id": user_a,
            "user_b_id": user_b,
            "turns": turns
        }
        
        conversations_list.append(conversation_obj)
        
        await asyncio.sleep(0)

    return {
        "conversations": conversations_list
    }


_IR_HOLIDAYS_CACHE: Dict[int, holidays.HolidayBase] = {}

async def _get_iran_holidays_for_year(year: int) -> holidays.HolidayBase:
    if year not in _IR_HOLIDAYS_CACHE:
        _IR_HOLIDAYS_CACHE[year] = holidays.IR(years=year)
    return _IR_HOLIDAYS_CACHE[year]


async def _normalize_to_iran_time(dt):
    if dt.tzinfo is not None:
        if dt.utcoffset() == timedelta(0):
            dt = dt.astimezone(ZoneInfo("Asia/Tehran"))
        dt = dt.replace(tzinfo=None)
    return dt


async def _convert_one_datetime(date_str: str) -> Dict[str, Any]:

    dt = parser.parse(date_str)
    input_iso = dt.strftime("%Y-%m-%dT%H:%M:%S")

    dt = await _normalize_to_iran_time(dt)


    gregorian_date = dt.strftime("%Y-%m-%d")

    jdt = jdatetime.datetime.fromgregorian(datetime=dt)
    jalali_date = jdt.strftime("%Y-%m-%d")

    time_str = dt.strftime("%H:%M:%S")

    weekday_index = dt.weekday()
    weekday_names_en = [
        "Monday", "Tuesday", "Wednesday",
        "Thursday", "Friday", "Saturday", "Sunday"
    ]
    weekday_names_fa = [
        "دوشنبه", "سه‌شنبه", "چهارشنبه",
        "پنج‌شنبه", "جمعه", "شنبه", "یکشنبه"
    ]

    weekday_fa = weekday_names_fa[weekday_index]

    ir_holidays = await _get_iran_holidays_for_year(dt.year)
    is_official_holiday = dt.date() in ir_holidays

    is_weekend = weekday_index in (3, 4)

    is_holiday = is_official_holiday or is_weekend

    return {
        "input_iso": input_iso,
        "gregorian_date": gregorian_date,
        "jalali_date": jalali_date,
        "time": time_str,
        "weekday_fa": weekday_fa,
        "is_holiday": is_holiday,
    }


async def gregorian_list_to_jalali_with_holiday(date_str_list: List[str]) -> List[Dict[str, Any]]:
    logger.debug("Converting %d dates to Jalali with holiday info", len(date_str_list))
    results: List[Dict[str, Any]] = []
    for s in date_str_list:
        results.append(await _convert_one_datetime(s))
    return results
