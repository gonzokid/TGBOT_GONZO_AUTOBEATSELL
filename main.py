import random
import time
import os
import json
import uuid
from datetime import datetime, date, timedelta
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
import logging
import re
import asyncio
from collections import defaultdict

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove, LabeledPrice
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    PreCheckoutQueryHandler, filters, ContextTypes, ConversationHandler, JobQueue
)

# ============ НАСТРОЙКИ ============
BOT_TOKEN = "8690704744:AAGTGrQYoE0Su3gbK1BOOxLCk8U6TqB1dnA"
SUPER_ADMIN_ID = 6756790622
SUPER_ADMIN_PASSWORD = "superbeat2024"

# Тарифы подписок
SUBSCRIPTION_TIERS = {
    "trial": {
        "name": "🎁 Пробный",
        "price": 0,
        "days": 7,
        "max_channels": 1,
        "collabs_allowed": False,
        "private_allowed": False,
        "samples_allowed": False,
        "description": "7 дней бесплатно, 1 канал"
    },
    "basic": {
        "name": "🔹 Базовый",
        "price": 200,
        "days": 30,
        "max_channels": 1,
        "collabs_allowed": False,
        "private_allowed": False,
        "samples_allowed": True,
        "description": "1 канал, продажа битов и сэмплов"
    },
    "premium": {
        "name": "💎 Премиум",
        "price": 500,
        "days": 30,
        "max_channels": 3,
        "collabs_allowed": True,
        "private_allowed": True,
        "samples_allowed": True,
        "description": "До 3 каналов, коллабы, приватный канал, сэмплы"
    }
}

# ============ СОСТОЯНИЯ ============
(
    MAIN_MENU, SUPER_ADMIN_MENU, BEATMAKER_MENU, CHANNEL_SELECT,
    ADD_BEAT_TITLE, ADD_BEAT_BPM, ADD_BEAT_KEY, ADD_BEAT_GENRE,
    ADD_BEAT_MOOD, ADD_BEAT_ARTIST, ADD_BEAT_COLLAB, ADD_BEAT_MP3, ADD_BEAT_COVER,
    ADD_BEAT_PRICES, ADD_BEAT_CONFIRM,
    ADD_SAMPLE_TITLE, ADD_SAMPLE_MP3, ADD_SAMPLE_PRICE, ADD_SAMPLE_CONFIRM,
    EDIT_PRICE_WAV, EDIT_PRICE_EXCLUSIVE, EDIT_PRICE_STEMS, EDIT_PRICE_SAMPLES,
    EDIT_GENRES, ADD_GENRE, REMOVE_GENRE,
    EDIT_SETTINGS, SELECT_BEAT_FOR_DELETE, SUBSCRIPTION_CONFIRM,
    MY_CHANNELS_MENU, CONTRACT_MENU, CONTRACT_TEMPLATE_EDIT,
    CONTRACT_SIGNATURE_WAIT, CONTRACT_VIEW, PRIVATE_CHANNEL_SETUP,
    SUPER_ADMIN_SETTINGS, EDIT_SUBSCRIPTION_PRICES
) = range(37)

# ============ ЛОГИРОВАНИЕ ============
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ============ МОДЕЛИ ДАННЫХ ============

@dataclass
class CollabBeatmaker:
    """Участник коллаба"""
    channel_username: str
    share_percent: int


@dataclass
class Beat:
    """Модель бита (все обязательные поля - первыми)"""
    id: str
    beatmaker_id: int
    title: str
    mp3_file_id: str
    cover_file_id: Optional[str] = None
    bpm: Optional[int] = None
    key: Optional[str] = None
    genre: Optional[str] = None
    mood: Optional[str] = None
    similar_artist: Optional[str] = None
    collaborators: List[CollabBeatmaker] = field(default_factory=list)
    price_wav: int = 50
    price_exclusive: int = 200
    price_stems: int = 100
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    is_active: bool = True
    purchases_count: int = 0


@dataclass
class Sample:
    """Модель сэмпла"""
    id: str
    beatmaker_id: int
    title: str
    mp3_file_id: str
    price: int = 30
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    is_active: bool = True
    purchases_count: int = 0


@dataclass
class PrivateChannel:
    """Приватный канал битмейкера"""
    beatmaker_id: int
    channel_id: str
    channel_username: str
    invite_link: str
    price_month: int = 100
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    is_active: bool = True


@dataclass
class PrivateChannelAccess:
    """Доступ пользователя к приватному каналу"""
    id: str
    beatmaker_id: int
    user_id: int
    channel_username: str
    expires_at: str
    is_active: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class BeatmakerChannel:
    """Канал битмейкера (может быть несколько у одного пользователя)"""
    channel_id: int  # hash от channel_username как уникальный ключ
    user_id: int
    channel_username: str
    channel_name: str = ""
    subscription_tier: str = "basic"  # trial, basic, premium
    subscription_expires: Optional[str] = None
    is_active: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # Настройки отображения
    show_bpm: bool = True
    show_key: bool = True
    show_genre: bool = True
    show_mood: bool = False
    show_similar_artist: bool = False
    show_collaborators: bool = True

    # Доступные жанры
    genres: List[str] = field(default_factory=lambda: ["Hip-Hop", "Trap", "R&B", "Drill", "Boom Bap"])

    # Цены по умолчанию
    price_wav_default: int = 50
    price_exclusive_default: int = 200
    price_stems_default: int = 100
    price_samples_default: int = 30

    # Приватный канал (если есть)
    private_channel: Optional[PrivateChannel] = None

    # Шаблон договора
    contract_template: str = field(default_factory=lambda: """
ДОГОВОР №{contract_number}
передачи исключительных прав на использование музыкального произведения

г. Москва                                                {date}

Гражданин РФ, {buyer_name}, паспорт: {buyer_passport}, 
именуемый в дальнейшем "Приобретатель", с одной стороны, и 
{beatmaker_name}, именуемый в дальнейшем "Правообладатель", с другой стороны, 
заключили настоящий договор о нижеследующем:

1. ПРЕДМЕТ ДОГОВОРА
1.1. Правообладатель передает, а Приобретатель принимает исключительные права 
на использование музыкального произведения "{beat_title}" в полном объеме.

2. ПРАВА И ОБЯЗАННОСТИ СТОРОН
2.1. Правообладатель гарантирует, что является единственным обладателем 
исключительных прав на произведение.
{коллабораторы}

3. ПЛАТЕЖИ
3.1. Стоимость передачи прав составляет {price} рублей.

4. ПОДПИСИ СТОРОН
__________________            __________________
(Правообладатель)             (Приобретатель)

Дата: {date}
""".strip())


@dataclass
class Order:
    """Модель заказа"""
    id: str
    channel_id: int
    user_id: int
    item_type: str  # 'beat', 'sample', 'private'
    item_id: str
    amount: int
    purchase_type: Optional[str] = None
    status: str = "pending"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    paid_at: Optional[str] = None
    delivered_at: Optional[str] = None
    contract_sent: bool = False
    contract_signed: bool = False
    contract_file_id: Optional[str] = None
    buyer_name: Optional[str] = None
    buyer_passport: Optional[str] = None


@dataclass
class SubscriptionOrder:
    """Заказ на подписку для канала"""
    id: str
    channel_id: int
    user_id: int
    tier: str
    amount: int
    days: int
    status: str = "pending"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    paid_at: Optional[str] = None
    expires_at: Optional[str] = None


@dataclass
class User:
    """Модель пользователя (покупателя)"""
    user_id: int
    username: str = ""
    first_name: str = ""
    last_name: str = ""
    phone: str = ""
    purchased_items: List[str] = field(default_factory=list)  # список ID заказов
    private_access: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class SuperAdmin:
    """Данные суперадмина"""
    user_id: int
    subscription_prices: Dict[str, int] = field(default_factory=lambda: {
        "trial": 0,
        "basic": 200,
        "premium": 500
    })
    total_revenue: int = 0
    trial_days: int = 7
# ============ БАЗА ДАННЫХ ============

class Database:
    """JSON-база данных"""

    def __init__(self):
        self.data_dir = "data"
        self._ensure_data_dir()
        self.channels: Dict[int, BeatmakerChannel] = self._load("channels.json", BeatmakerChannel, key_type=int)
        self.beats: Dict[str, Beat] = self._load("beats.json", Beat)
        self.samples: Dict[str, Sample] = self._load("samples.json", Sample)
        self.private_access: Dict[str, PrivateChannelAccess] = self._load("private_access.json", PrivateChannelAccess)
        self.orders: Dict[str, Order] = self._load("orders.json", Order)
        self.sub_orders: Dict[str, SubscriptionOrder] = self._load("subscription_orders.json", SubscriptionOrder)
        self.users: Dict[int, User] = self._load("users.json", User, key_type=int)
        self.super_admin = self._load_super_admin()

    def _ensure_data_dir(self):
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)

    def _load(self, filename, cls, key_type=str):
        filepath = os.path.join(self.data_dir, filename)
        if not os.path.exists(filepath):
            return {}
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                result = {}
                for k, v in data.items():
                    try:
                        if key_type == int:
                            k = int(k)
                        if 'collaborators' in v and cls == Beat:
                            collabs = []
                            for c in v['collaborators']:
                                if isinstance(c, dict):
                                    collabs.append(CollabBeatmaker(**c))
                            v['collaborators'] = collabs
                        result[k] = cls(**v)
                    except Exception as e:
                        logger.error(f"Ошибка загрузки {k}: {e}")
                return result
        except Exception as e:
            logger.error(f"Ошибка загрузки {filename}: {e}")
            return {}

    def _save(self, filename, data):
        filepath = os.path.join(self.data_dir, filename)
        try:
            serializable = {}
            for k, v in data.items():
                if hasattr(v, '__dict__'):
                    d = v.__dict__.copy()
                    if 'collaborators' in d:
                        d['collaborators'] = [c.__dict__ for c in d['collaborators']]
                    serializable[str(k)] = d
                else:
                    serializable[str(k)] = v
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(serializable, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения {filename}: {e}")

    def _load_super_admin(self):
        filepath = os.path.join(self.data_dir, "super_admin.json")
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return SuperAdmin(**data)
            except:
                pass
        return SuperAdmin(user_id=SUPER_ADMIN_ID)

    def _save_super_admin(self):
        filepath = os.path.join(self.data_dir, "super_admin.json")
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(self.super_admin.__dict__, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения суперадмина: {e}")

    # ===== КАНАЛЫ =====

    def get_channel(self, channel_id: int) -> Optional[BeatmakerChannel]:
        return self.channels.get(channel_id)

    def get_channel_by_username(self, channel_username: str) -> Optional[BeatmakerChannel]:
        for ch in self.channels.values():
            if ch.channel_username == channel_username:
                return ch
        return None

    def get_user_channels(self, user_id: int) -> List[BeatmakerChannel]:
        return [ch for ch in self.channels.values() if ch.user_id == user_id]

    def add_channel(self, user_id: int, channel_id: str, channel_username: str,
                    tier: str = "trial") -> BeatmakerChannel:
        # Проверяем, нет ли уже такого канала
        for ch in self.channels.values():
            if ch.channel_username == channel_username:
                return ch

        # Генерируем ID для канала
        ch_id = hash(channel_username)

        # Рассчитываем дату окончания подписки
        expires = None
        if tier != "trial" or tier == "trial":
            days = self.super_admin.trial_days if tier == "trial" else 30
            expires = (datetime.now() + timedelta(days=days)).isoformat()

        channel = BeatmakerChannel(
            channel_id=ch_id,
            user_id=user_id,
            channel_username=channel_username,
            subscription_tier=tier,
            subscription_expires=expires
        )
        self.channels[ch_id] = channel
        self._save("channels.json", self.channels)
        return channel

    def update_channel(self, channel_username: str, **kwargs):
        for ch in self.channels.values():
            if ch.channel_username == channel_username:
                for key, value in kwargs.items():
                    if hasattr(ch, key):
                        setattr(ch, key, value)
                self._save("channels.json", self.channels)
                return True
        return False

    def remove_channel(self, channel_username: str) -> bool:
        key_to_remove = None
        for k, ch in self.channels.items():
            if ch.channel_username == channel_username:
                key_to_remove = k
                break
        if key_to_remove:
            del self.channels[key_to_remove]
            self._save("channels.json", self.channels)
            return True
        return False

    def get_active_channels(self) -> List[BeatmakerChannel]:
        today = datetime.now().isoformat()
        return [ch for ch in self.channels.values()
                if ch.is_active and (ch.subscription_expires is None or ch.subscription_expires > today)]

    def check_subscription(self, channel_username: str) -> Tuple[bool, Optional[int]]:
        """Проверяет подписку канала, возвращает (активна, дней до окончания)"""
        ch = self.get_channel_by_username(channel_username)
        if not ch or not ch.is_active:
            return False, None
        if not ch.subscription_expires:
            return True, 999  # бессрочно
        expires = datetime.fromisoformat(ch.subscription_expires)
        now = datetime.now()
        if expires < now:
            return False, None
        days_left = (expires - now).days
        return True, days_left

    def extend_subscription(self, channel_username: str, days: int):
        """Продлевает подписку канала"""
        ch = self.get_channel_by_username(channel_username)
        if ch:
            if ch.subscription_expires:
                current = datetime.fromisoformat(ch.subscription_expires)
                new_expires = current + timedelta(days=days)
            else:
                new_expires = datetime.now() + timedelta(days=days)
            ch.subscription_expires = new_expires.isoformat()
            self._save("channels.json", self.channels)
            return True
        return False

    # ===== БИТЫ =====

    def add_beat(self, beat: Beat):
        self.beats[beat.id] = beat
        self._save("beats.json", self.beats)
        return beat

    def get_beat(self, beat_id: str) -> Optional[Beat]:
        return self.beats.get(beat_id)

    def get_channel_beats(self, channel_id: int) -> List[Beat]:
        return [b for b in self.beats.values() if b.beatmaker_id == channel_id]

    def get_all_active_beats(self) -> List[Beat]:
        return [b for b in self.beats.values() if b.is_active]

    def update_beat(self, beat_id: str, **kwargs):
        beat = self.beats.get(beat_id)
        if beat:
            for key, value in kwargs.items():
                if hasattr(beat, key):
                    setattr(beat, key, value)
            self._save("beats.json", self.beats)
            return True
        return False

    def delete_beat(self, beat_id: str):
        beat = self.beats.get(beat_id)
        if beat:
            beat.is_active = False
            self._save("beats.json", self.beats)
            return True
        return False

    # ===== СЭМПЛЫ =====

    def add_sample(self, sample: Sample):
        self.samples[sample.id] = sample
        self._save("samples.json", self.samples)
        return sample

    def get_sample(self, sample_id: str) -> Optional[Sample]:
        return self.samples.get(sample_id)

    def get_channel_samples(self, channel_id: int) -> List[Sample]:
        return [s for s in self.samples.values() if s.beatmaker_id == channel_id]

    def get_all_active_samples(self) -> List[Sample]:
        return [s for s in self.samples.values() if s.is_active]

    def update_sample(self, sample_id: str, **kwargs):
        sample = self.samples.get(sample_id)
        if sample:
            for key, value in kwargs.items():
                if hasattr(sample, key):
                    setattr(sample, key, value)
            self._save("samples.json", self.samples)
            return True
        return False

    def delete_sample(self, sample_id: str):
        sample = self.samples.get(sample_id)
        if sample:
            sample.is_active = False
            self._save("samples.json", self.samples)
            return True
        return False

    # ===== ПРИВАТНЫЕ КАНАЛЫ =====

    def set_private_channel(self, channel_id: int, private_id: str, private_username: str,
                            invite_link: str, price_month: int) -> PrivateChannel:
        private = PrivateChannel(
            beatmaker_id=channel_id,
            channel_id=private_id,
            channel_username=private_username,
            invite_link=invite_link,
            price_month=price_month
        )
        ch = self.channels.get(channel_id)
        if ch:
            ch.private_channel = private
            self._save("channels.json", self.channels)
        return private

    def grant_private_access(self, channel_id: int, user_id: int, private_username: str,
                             months: int) -> PrivateChannelAccess:
        access_id = str(uuid.uuid4())[:8]
        expires = (datetime.now() + timedelta(days=30 * months)).isoformat()
        access = PrivateChannelAccess(
            id=access_id,
            beatmaker_id=channel_id,
            user_id=user_id,
            channel_username=private_username,
            expires_at=expires
        )
        self.private_access[access_id] = access
        self._save("private_access.json", self.private_access)

        user = self.get_user(user_id)
        if private_username not in user.private_access:
            user.private_access.append(private_username)
            self._save("users.json", self.users)

        return access

    def check_private_access(self, user_id: int, private_username: str) -> bool:
        for access in self.private_access.values():
            if access.user_id == user_id and access.channel_username == private_username and access.is_active:
                if access.expires_at > datetime.now().isoformat():
                    return True
        return False

    # ===== ПОЛЬЗОВАТЕЛИ =====

    def get_user(self, user_id: int) -> User:
        if user_id not in self.users:
            self.users[user_id] = User(user_id=user_id)
            self._save("users.json", self.users)
        return self.users[user_id]

    def update_user(self, user_id: int, **kwargs):
        user = self.users.get(user_id)
        if user:
            for key, value in kwargs.items():
                if hasattr(user, key):
                    setattr(user, key, value)
            self._save("users.json", self.users)
            return True
        return False

    # ===== ЗАКАЗЫ =====

    def create_order(self, channel_id: int, item_type: str, item_id: str, user_id: int,
                     amount: int, purchase_type: Optional[str] = None) -> Order:
        order_id = str(uuid.uuid4())[:8]
        order = Order(
            id=order_id,
            channel_id=channel_id,
            item_type=item_type,
            item_id=item_id,
            user_id=user_id,
            purchase_type=purchase_type,
            amount=amount,
            status='pending'
        )
        self.orders[order_id] = order
        self._save("orders.json", self.orders)
        return order

    def get_order(self, order_id: str) -> Optional[Order]:
        return self.orders.get(order_id)

    def get_channel_orders(self, channel_id: int) -> List[Order]:
        return [o for o in self.orders.values() if o.channel_id == channel_id]

    def get_user_orders(self, user_id: int) -> List[Order]:
        return [o for o in self.orders.values() if o.user_id == user_id]

    def update_order_status(self, order_id: str, status: str):
        order = self.orders.get(order_id)
        if order:
            order.status = status
            if status == 'paid':
                order.paid_at = datetime.now().isoformat()
                # Добавляем пользователю в историю
                user = self.get_user(order.user_id)
                if order.order_id not in user.purchased_items:
                    user.purchased_items.append(order.order_id)
                    self._save("users.json", self.users)
            elif status == 'delivered':
                order.delivered_at = datetime.now().isoformat()
            self._save("orders.json", self.orders)
            return True
        return False

    def update_order(self, order_id: str, **kwargs):
        order = self.orders.get(order_id)
        if order:
            for key, value in kwargs.items():
                if hasattr(order, key):
                    setattr(order, key, value)
            self._save("orders.json", self.orders)
            return True
        return False

    # ===== ПОДПИСКИ =====

    def create_subscription_order(self, channel_id: int, user_id: int, tier: str, days: int) -> SubscriptionOrder:
        order_id = str(uuid.uuid4())[:8]
        price = self.super_admin.subscription_prices[tier] * (days // 30) if days >= 30 else \
        self.super_admin.subscription_prices[tier]
        order = SubscriptionOrder(
            id=order_id,
            channel_id=channel_id,
            user_id=user_id,
            tier=tier,
            amount=price,
            days=days,
            status='pending'
        )
        self.sub_orders[order_id] = order
        self._save("subscription_orders.json", self.sub_orders)
        return order

    def get_subscription_order(self, order_id: str) -> Optional[SubscriptionOrder]:
        return self.sub_orders.get(order_id)

    def activate_subscription(self, order_id: str):
        order = self.sub_orders.get(order_id)
        if order:
            order.status = 'active'
            order.paid_at = datetime.now().isoformat()

            # Находим канал и обновляем подписку
            for ch in self.channels.values():
                if ch.channel_id == order.channel_id:
                    if ch.subscription_expires:
                        current = datetime.fromisoformat(ch.subscription_expires)
                        new_expires = current + timedelta(days=order.days)
                    else:
                        new_expires = datetime.now() + timedelta(days=order.days)
                    ch.subscription_expires = new_expires.isoformat()
                    ch.subscription_tier = order.tier
                    break

            self._save("channels.json", self.channels)
            self._save("subscription_orders.json", self.sub_orders)

            self.super_admin.total_revenue += order.amount
            self._save_super_admin()

            return True
        return False


# ============ ИНИЦИАЛИЗАЦИЯ ============
db = Database()


# ============ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ============

def is_super_admin(user_id: int) -> bool:
    return user_id == SUPER_ADMIN_ID


def get_channel_id(channel_username: str) -> int:
    return hash(channel_username)


def format_beat_caption(beat: Beat, channel: BeatmakerChannel) -> str:
    caption = f"🔥 **НОВЫЙ БИТ**\n\n🎵 **{beat.title}**"

    if channel.show_bpm and beat.bpm:
        caption += f"\n⚡ BPM: {beat.bpm}"
    if channel.show_key and beat.key:
        caption += f"\n🎹 Тональность: {beat.key}"
    if channel.show_genre and beat.genre:
        caption += f"\n🎼 Жанр: {beat.genre}"
    if channel.show_mood and beat.mood:
        caption += f"\n🎭 Настроение: {beat.mood}"
    if channel.show_similar_artist and beat.similar_artist:
        caption += f"\n🎤 В стиле: {beat.similar_artist}"
    if channel.show_collaborators and beat.collaborators:
        collabs = ", ".join([c.channel_username for c in beat.collaborators])
        caption += f"\n🤝 Коллаб: {collabs}"

    caption += f"\n\n💰 **Цены:**\n• WAV: {beat.price_wav} ⭐\n• Эксклюзив: {beat.price_exclusive} ⭐\n• Стэмзы: {beat.price_stems} ⭐"

    return caption


def get_beat_keyboard(beat_id: str) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("WAV", callback_data=f"buy_beat_{beat_id}_wav"),
            InlineKeyboardButton("Эксклюзив", callback_data=f"buy_beat_{beat_id}_exclusive"),
            InlineKeyboardButton("Стэмзы", callback_data=f"buy_beat_{beat_id}_stems"),
        ],
        [InlineKeyboardButton("ℹ️ Подробнее", callback_data=f"info_beat_{beat_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_sample_keyboard(sample_id: str) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("Купить сэмпл", callback_data=f"buy_sample_{sample_id}")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_private_keyboard(channel_username: str, price: int) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(f"Доступ на 1 месяц — {price} ⭐",
                              callback_data=f"buy_private_{channel_username}_1")],
        [InlineKeyboardButton(f"Доступ на 3 месяца — {price * 3} ⭐",
                              callback_data=f"buy_private_{channel_username}_3")],
        [InlineKeyboardButton(f"Доступ на 6 месяцев — {price * 6} ⭐",
                              callback_data=f"buy_private_{channel_username}_6")],
        [InlineKeyboardButton(f"Доступ на 12 месяцев — {price * 12} ⭐",
                              callback_data=f"buy_private_{channel_username}_12")],
    ]
    return InlineKeyboardMarkup(keyboard)


def generate_contract_number() -> str:
    return f"BEAT-{datetime.now().strftime('%Y%m')}-{random.randint(1000, 9999)}"


def generate_contract(beat: Beat, order: Order, buyer: User, channel: BeatmakerChannel) -> str:
    template = channel.contract_template

    collab_text = ""
    if beat.collaborators:
        collab_text = "\n".join([f"Соавтор: {c.channel_username} ({c.share_percent}%)" for c in beat.collaborators])

    replacements = {
        "{contract_number}": generate_contract_number(),
        "{date}": datetime.now().strftime("%d.%m.%Y"),
        "{buyer_name}": buyer.first_name + " " + (buyer.last_name or ""),
        "{buyer_passport}": buyer.phone or "данные паспорта не указаны",
        "{beatmaker_name}": channel.channel_username,
        "{beat_title}": beat.title,
        "{price}": str(order.amount),
        "{коллабораторы}": collab_text
    }

    contract = template
    for key, value in replacements.items():
        contract = contract.replace(key, value)

    return contract


# ============ УВЕДОМЛЕНИЯ О ПОДПИСКЕ ============

async def check_subscriptions(context: ContextTypes.DEFAULT_TYPE):
    """Проверяет подписки и отправляет уведомления"""
    now = datetime.now()

    for channel in db.channels.values():
        if not channel.subscription_expires:
            continue

        expires = datetime.fromisoformat(channel.subscription_expires)
        days_left = (expires - now).days

        if days_left in [15, 10, 5, 3, 2, 1]:
            # Отправляем уведомление владельцу
            try:
                text = f"⚠️ **Подписка канала {channel.channel_username} истекает через {days_left} дней!**\n\n"
                text += f"Продли подписку, чтобы продолжить продажи.\n"
                text += f"/subscribe_{channel.channel_username} — продлить"

                await context.bot.send_message(
                    chat_id=channel.user_id,
                    text=text,
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.error(f"Ошибка уведомления {channel.user_id}: {e}")

        elif days_left == 0:
            # Подписка истекла
            channel.is_active = False
            db._save("channels.json", db.channels)

            try:
                await context.bot.send_message(
                    chat_id=channel.user_id,
                    text=f"❌ **Подписка канала {channel.channel_username} истекла!**\n\n"
                         f"Товары больше не публикуются. Продли подписку чтобы восстановить доступ.",
                    parse_mode=ParseMode.MARKDOWN
                )
            except:
                pass


# ============ ОБРАБОТЧИКИ КОМАНД ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = db.get_user(user.id)
    db_user.username = user.username or ""
    db_user.first_name = user.first_name or ""
    db_user.last_name = user.last_name or ""
    db.update_user(user.id,
                   username=user.username or "",
                   first_name=user.first_name or "",
                   last_name=user.last_name or "")

    channels = db.get_user_channels(user.id)

    if is_super_admin(user.id):
        text = f"👑 **Привет, Повелитель битов {user.first_name}!**\n\n"
        text += f"У тебя {len(channels)} каналов"
        keyboard = [["👑 Панель суперадмина"]]
    elif channels:
        text = f"🎵 **Привет, {user.first_name}!**\n\n"
        text += f"Твои каналы:\n"
        for ch in channels:
            active, days = db.check_subscription(ch.channel_username)
            status = "✅" if active else "❌"
            text += f"{status} {ch.channel_username}"
            if days and days < 30:
                text += f" (осталось {days} дн.)"
            text += "\n"
        text += "\nВыбери канал для управления:"
        keyboard = [[ch.channel_username] for ch in channels]
        keyboard.append(["➕ Новый канал"])
    else:
        text = f"👋 **Привет, {user.first_name}!**\n\n"
        text += f"Добро пожаловать в битмейкер-платформу!\n\n"
        text += f"🔍 **Для покупателей:**\n/catalog — все биты и сэмплы\n/my_purchases — мои покупки\n"
        text += f"🎧 **Для битмейкеров:**\n/subscribe — оформить подписку"
        keyboard = [["/catalog", "/my_purchases"], ["/subscribe"]]

    keyboard.append(["/help"])

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return MAIN_MENU


async def catalog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    beats = db.get_all_active_beats()
    samples = db.get_all_active_samples()

    text = "🎵 **ВСЕ ТОВАРЫ**\n\n"

    if beats:
        text += "**🎵 БИТЫ:**\n"
        beat_by_channel = defaultdict(list)
        for beat in beats:
            ch = db.get_channel(beat.beatmaker_id)
            if ch:
                beat_by_channel[ch.channel_username].append(beat)

        for ch_name, ch_beats in beat_by_channel.items():
            text += f"📢 {ch_name}: {len(ch_beats)} битов\n"

    if samples:
        text += "\n**🎧 СЭМПЛЫ:**\n"
        sample_by_channel = defaultdict(list)
        for sample in samples:
            ch = db.get_channel(sample.beatmaker_id)
            if ch:
                sample_by_channel[ch.channel_username].append(sample)

        for ch_name, ch_samples in sample_by_channel.items():
            text += f"📢 {ch_name}: {len(ch_samples)} сэмплов\n"

    text += "\n👉 Заходи в каналы битмейкеров и покупай!"

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    return MAIN_MENU


async def my_purchases(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    orders = db.get_user_orders(user_id)

    if not orders:
        await update.message.reply_text("📭 У тебя пока нет покупок.")
        return MAIN_MENU

    text = "📋 **ТВОИ ПОКУПКИ**\n\n"
    for order in orders[-10:]:
        if order.item_type == 'beat':
            beat = db.get_beat(order.item_id)
            if beat:
                contract_status = "📄 Подписан" if order.contract_signed else "⏳ Ожидает"
                text += f"• Бит: {beat.title} — {order.purchase_type}\n"
                text += f"  Статус: {contract_status}\n"
        elif order.item_type == 'sample':
            sample = db.get_sample(order.item_id)
            if sample:
                text += f"• Сэмпл: {sample.title}\n"

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    return MAIN_MENU


async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "💰 **ВЫБЕРИ ТАРИФ ПОДПИСКИ**\n\n"

    keyboard = []
    for tier, info in SUBSCRIPTION_TIERS.items():
        text += f"{info['name']}: {info['price']} ⭐/мес\n"
        text += f"  {info['description']}\n\n"
        keyboard.append([InlineKeyboardButton(info['name'], callback_data=f"sub_select_{tier}")])

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return MAIN_MENU


async def subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.split('_')
    action = data[1]

    if action == 'select':
        tier = data[2]
        context.user_data['selected_tier'] = tier

        await query.edit_message_text(
            f"📢 **ПОСЛЕДНИЙ ШАГ**\n\n"
            f"Отправь @username своего канала.\n\n"
            f"Если хочешь попробовать — выбери пробный период 7 дней бесплатно!\n\n"
            f"Или выбери платный тариф:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🔹 Базовый 200⭐", callback_data="sub_pay_basic")],
                [InlineKeyboardButton(f"💎 Премиум 500⭐", callback_data="sub_pay_premium")],
            ])
        )

    elif action == 'pay':
        tier = data[2]
        context.user_data['selected_tier'] = tier
        context.user_data['awaiting_channel'] = True

        await query.edit_message_text(
            f"📢 Отправь @username своего канала.\n"
            f"Например: @mychannel"
        )


async def subscription_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_channel'):
        return MAIN_MENU

    channel_input = update.message.text.strip()
    user_id = update.effective_user.id

    if not channel_input.startswith('@'):
        channel_input = '@' + channel_input

    tier = context.user_data.get('selected_tier', 'basic')

    # Проверяем, есть ли уже такой канал
    existing = db.get_channel_by_username(channel_input)
    if existing and existing.user_id != user_id:
        await update.message.reply_text("❌ Этот канал уже занят другим пользователем!")
        return MAIN_MENU

    context.user_data['channel_username'] = channel_input

    if tier == 'trial':
        # Бесплатный пробный период
        channel = db.add_channel(user_id, channel_input, channel_input, tier='trial')
        await update.message.reply_text(
            f"✅ Пробный период активирован!\n\n"
            f"Канал: {channel_input}\n"
            f"Дней осталось: {db.super_admin.trial_days}\n\n"
            f"Теперь ты можешь добавлять биты!",
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data['awaiting_channel'] = False
    else:
        # Платный тариф - отправляем инвойс
        channel_id = get_channel_id(channel_input)
        days = 30
        order = db.create_subscription_order(channel_id, user_id, tier, days)

        await context.bot.send_invoice(
            chat_id=update.effective_chat.id,
            title=f"Подписка {SUBSCRIPTION_TIERS[tier]['name']}",
            description=f"Активация подписки для канала {channel_input}",
            payload=order.id,
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="Подписка", amount=order.amount)]
        )
        context.user_data['awaiting_channel'] = False

    return MAIN_MENU


# ============ ПАНЕЛЬ СУПЕРАДМИНА ============

async def super_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_super_admin(user_id):
        await update.message.reply_text("⛔ Доступ запрещен!")
        return MAIN_MENU
    return await show_super_admin_menu(update, context)


async def show_super_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    channels = db.get_active_channels()
    total_revenue = db.super_admin.total_revenue

    text = f"""
👑 **ПАНЕЛЬ СУПЕРАДМИНА**

📊 **Статистика:**
• Активных каналов: {len(channels)}
• Всего выручка: {total_revenue} ⭐
• Всего битов: {len(db.beats)}
• Всего сэмплов: {len(db.samples)}

⚙️ **Настройки:**
/price_edit — изменить цены подписок
/trial_edit — изменить пробный период
    """

    keyboard = [
        ["📋 Список каналов", "➕ Добавить канал"],
        ["📊 Статистика", "💰 Доходы"],
        ["📢 Мои каналы", "⚙️ Настройки цен"],
        ["❌ Выход"]
    ]

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return SUPER_ADMIN_MENU


async def super_admin_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if not is_super_admin(user_id):
        await update.message.reply_text("⛔ Доступ запрещен!")
        return MAIN_MENU

    if text == "📋 Список каналов":
        channels = db.channels.values()
        if not channels:
            await update.message.reply_text("📭 Нет каналов")
        else:
            text = "📋 **ВСЕ КАНАЛЫ**\n\n"
            for ch in channels:
                active, days = db.check_subscription(ch.channel_username)
                status = "✅" if active else "❌"
                text += f"{status} {ch.channel_username}\n"
                text += f"   Владелец: {ch.user_id}\n"
                text += f"   Тариф: {ch.subscription_tier}\n"
                text += f"   Дней осталось: {days if days else '∞'}\n\n"
            await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

    elif text == "➕ Добавить канал":
        await update.message.reply_text(
            "📝 Отправь ID пользователя и @username канала через пробел:\n"
            "Пример: `6756790622 @mychannel`\n\n"
            "Битмейкер получит пробный период.",
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data['expecting_new_channel'] = True
        return SUPER_ADMIN_MENU

    elif text == "📊 Статистика":
        beats = len(db.beats)
        samples = len(db.samples)
        orders = len([o for o in db.orders.values() if o.status == 'paid'])
        revenue = db.super_admin.total_revenue

        await update.message.reply_text(
            f"📊 **ОБЩАЯ СТАТИСТИКА**\n\n"
            f"Каналов: {len(db.channels)}\n"
            f"Активных: {len(db.get_active_channels())}\n"
            f"Битов: {beats}\n"
            f"Сэмплов: {samples}\n"
            f"Продаж: {orders}\n"
            f"Выручка: {revenue} ⭐",
            parse_mode=ParseMode.MARKDOWN
        )

    elif text == "💰 Доходы":
        await update.message.reply_text(
            f"💰 **ДОХОДЫ ОТ ПОДПИСОК**\n\n"
            f"Всего: {db.super_admin.total_revenue} ⭐",
            parse_mode=ParseMode.MARKDOWN
        )

    elif text == "📢 Мои каналы":
        return await show_my_channels_menu(update, context)

    elif text == "⚙️ Настройки цен":
        return await show_price_settings(update, context)

    elif text == "❌ Выход":
        await update.message.reply_text(
            "Выход из панели.",
            reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True)
        )
        return MAIN_MENU

    return SUPER_ADMIN_MENU


async def add_channel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('expecting_new_channel'):
        return SUPER_ADMIN_MENU

    text = update.message.text.strip()
    parts = text.split()

    if len(parts) != 2:
        await update.message.reply_text(
            "❌ Неверный формат. Отправь ID и @username канала через пробел.",
            parse_mode=ParseMode.MARKDOWN
        )
        return SUPER_ADMIN_MENU

    try:
        user_id = int(parts[0])
        channel_username = parts[1]

        # Добавляем канал с пробным периодом
        channel = db.add_channel(user_id, channel_username, channel_username, tier='trial')

        # Уведомляем пользователя
        try:
            expires = datetime.fromisoformat(channel.subscription_expires).strftime("%d.%m.%Y")
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🎉 **Вам открыт доступ к битмейкер-платформе!**\n\n"
                     f"📢 Канал: {channel_username}\n"
                     f"✅ Пробный период до: {expires}\n\n"
                     f"Напишите /start чтобы начать!",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")

        await update.message.reply_text(
            f"✅ Канал добавлен!\n\n"
            f"Владелец ID: {user_id}\n"
            f"Канал: {channel_username}\n"
            f"Пробный период: {db.super_admin.trial_days} дней",
            parse_mode=ParseMode.MARKDOWN
        )

        context.user_data['expecting_new_channel'] = False

    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом.")
        return SUPER_ADMIN_MENU

    return await show_super_admin_menu(update, context)


async def show_price_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "⚙️ **НАСТРОЙКА ЦЕН ПОДПИСОК**\n\n"

    for tier, info in SUBSCRIPTION_TIERS.items():
        current = db.super_admin.subscription_prices.get(tier, info['price'])
        text += f"{info['name']}: {current} ⭐ (было {info['price']})\n"

    text += "\nВведи новые цены в формате:\n"
    text += "`basic премиум trial`\n"
    text += "Например: 250 600 0"

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardMarkup([["❌ Отмена"]], resize_keyboard=True)
    )
    return EDIT_SUBSCRIPTION_PRICES


async def save_price_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "❌ Отмена":
        return await show_super_admin_menu(update, context)

    try:
        prices = text.split()
        if len(prices) != 3:
            raise ValueError("Нужно 3 числа")

        basic = int(prices[0])
        premium = int(prices[1])
        trial = int(prices[2])

        db.super_admin.subscription_prices = {
            "trial": trial,
            "basic": basic,
            "premium": premium
        }
        db._save_super_admin()

        # Обновляем глобальные настройки
        SUBSCRIPTION_TIERS["basic"]["price"] = basic
        SUBSCRIPTION_TIERS["premium"]["price"] = premium
        SUBSCRIPTION_TIERS["trial"]["price"] = trial

        await update.message.reply_text(
            f"✅ Цены обновлены!\n\n"
            f"Базовый: {basic} ⭐\n"
            f"Премиум: {premium} ⭐\n"
            f"Пробный: {trial} ⭐",
            parse_mode=ParseMode.MARKDOWN
        )
    except:
        await update.message.reply_text("❌ Неверный формат! Введи 3 числа через пробел.")
        return EDIT_SUBSCRIPTION_PRICES

    return await show_super_admin_menu(update, context)


async def show_my_channels_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    my_channels = db.get_user_channels(user_id)

    text = "📢 **МОИ КАНАЛЫ**\n\n"

    if my_channels:
        for i, ch in enumerate(my_channels, 1):
            active, days = db.check_subscription(ch.channel_username)
            status = "✅" if active else "❌"
            beats = len(db.get_channel_beats(ch.channel_id))
            samples = len(db.get_channel_samples(ch.channel_id))
            text += f"{i}. {status} {ch.channel_username}\n"
            text += f"   Битов: {beats}, Сэмплов: {samples}\n"
            if days and days < 30:
                text += f"   ⏳ Осталось: {days} дн.\n"
            text += "\n"
    else:
        text += "У тебя пока нет своих каналов.\n\n"

    text += "➕ Добавить канал — отправь @username\n"
    text += "➖ Удалить канал — отправь номер канала\n"
    text += "👉 Управлять каналом — нажми на его название"

    keyboard = [["❌ Назад"]]

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    context.user_data['in_my_channels'] = True
    return MY_CHANNELS_MENU


async def my_channels_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    # Логируем для отладки
    logger.info(f"my_channels_handler: получил текст '{text}' от пользователя {user_id}")

    if text == "❌ Назад":
        logger.info("Пользователь нажал Назад")
        context.user_data['in_my_channels'] = False
        return await show_super_admin_menu(update, context)

    my_channels = db.get_user_channels(user_id)
    logger.info(f"Найдено каналов у пользователя: {len(my_channels)}")

    # Проверяем, не выбрал ли пользователь канал для управления
    for ch in my_channels:
        logger.info(f"Сравниваем с каналом: '{ch.channel_username}'")
        if text == ch.channel_username:
            logger.info(f"СОВПАДЕНИЕ! Выбран канал: {ch.channel_username}")
            context.user_data['current_channel'] = ch.channel_username
            # Переходим в панель управления каналом
            return await show_beatmaker_menu(update, context, ch)

    # Проверяем, не ввел ли пользователь номер для удаления
    try:
        channel_num = int(text)
        logger.info(f"Пользователь ввел число: {channel_num}")
        if 1 <= channel_num <= len(my_channels):
            ch_to_remove = my_channels[channel_num - 1]
            logger.info(f"Удаляем канал: {ch_to_remove.channel_username}")
            if db.remove_channel(ch_to_remove.channel_username):
                await update.message.reply_text(
                    f"✅ Канал {ch_to_remove.channel_username} удален.",
                    parse_mode=ParseMode.MARKDOWN
                )
            return await show_my_channels_menu(update, context)
    except ValueError:
        logger.info("Пользователь ввел не число, а текст")

    # Добавление нового канала
    channel_username = text.strip()
    if not channel_username.startswith('@'):
        channel_username = '@' + channel_username
    logger.info(f"Попытка добавить канал: {channel_username}")

    # Проверяем, нет ли уже такого канала
    for ch in my_channels:
        if ch.channel_username == channel_username:
            logger.info(f"Канал {channel_username} уже существует")
            await update.message.reply_text(f"❌ Канал {channel_username} уже есть.")
            return MY_CHANNELS_MENU

    # Добавляем канал с бессрочной подпиской
    db.add_channel(
        user_id=user_id,
        channel_id=channel_username,
        channel_username=channel_username,
        tier="premium"
    )
    logger.info(f"Канал {channel_username} успешно добавлен")

    await update.message.reply_text(
        f"✅ Канал {channel_username} добавлен!\n"
        f"Теперь ты можешь управлять им.",
        parse_mode=ParseMode.MARKDOWN
    )

    return await show_my_channels_menu(update, context)


# ============ ПАНЕЛЬ БИТМЕЙКЕРА ============

async def show_beatmaker_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, channel: BeatmakerChannel):
    logger.info(f"Переход в панель управления каналом: {channel.channel_username}")
    beats = db.get_channel_beats(channel.channel_id)
    samples = db.get_channel_samples(channel.channel_id)
    orders = db.get_channel_orders(channel.channel_id)
    pending_contracts = len([o for o in orders if o.contract_sent and not o.contract_signed])

    active, days_left = db.check_subscription(channel.channel_username)

    text = f"""
🎵 **ПАНЕЛЬ УПРАВЛЕНИЯ КАНАЛОМ**

📢 Канал: {channel.channel_username}
💎 Тариф: {channel.subscription_tier}
⏳ Подписка: {'∞' if not days_left else f'{days_left} дн.'}

📊 **Статистика:**
• Битов: {len(beats)}
• Сэмплов: {len(samples)}
• Продаж: {len([o for o in orders if o.status == 'paid'])}
• Договоров к подписи: {pending_contracts}

Выбери действие:
    """

    keyboard = [
        ["➕ Добавить бит", "🎧 Добавить сэмпл"],
        ["💰 Цены", "🎼 Жанры"],
        ["⚙️ Настройки", "📊 Статистика"],
        ["📋 Мои товары", "📄 Договоры"],
        ["🔐 Приватный канал", "❌ Назад"]
    ]

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return BEATMAKER_MENU


async def beatmaker_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    current_channel = context.user_data.get('current_channel')
    if not current_channel:
        return await start(update, context)

    channel = db.get_channel_by_username(current_channel)
    if not channel:
        await update.message.reply_text("❌ Канал не найден.")
        return MAIN_MENU

    if text == "➕ Добавить бит":
        context.user_data['new_beat'] = {'beatmaker_id': channel.channel_id}
        await update.message.reply_text(
            "🎵 **ДОБАВЛЕНИЕ БИТА**\n\n"
            "Введите название бита:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=ReplyKeyboardMarkup([["❌ Отмена"]], resize_keyboard=True)
        )
        return ADD_BEAT_TITLE

    elif text == "🎧 Добавить сэмпл":
        context.user_data['new_sample'] = {'beatmaker_id': channel.channel_id}
        await update.message.reply_text(
            "🎧 **ДОБАВЛЕНИЕ СЭМПЛА**\n\n"
            "Введите название сэмпла:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=ReplyKeyboardMarkup([["❌ Отмена"]], resize_keyboard=True)
        )
        return ADD_SAMPLE_TITLE

    elif text == "💰 Цены":
        price_text = f"💰 **ТЕКУЩИЕ ЦЕНЫ**\n\n"
        price_text += f"WAV: {channel.price_wav_default} ⭐\n"
        price_text += f"Эксклюзив: {channel.price_exclusive_default} ⭐\n"
        price_text += f"Стэмзы: {channel.price_stems_default} ⭐\n"
        price_text += f"Сэмплы: {channel.price_samples_default} ⭐\n\n"
        price_text += "Изменить: /edit_prices"
        await update.message.reply_text(price_text, parse_mode=ParseMode.MARKDOWN)

    elif text == "🎼 Жанры":
        genres = channel.genres
        genre_text = "🎼 **ТВОИ ЖАНРЫ**\n\n"
        for i, genre in enumerate(genres, 1):
            genre_text += f"{i}. {genre}\n"
        genre_text += "\n➕ Добавить — отправь название\n➖ Удалить — отправь номер"
        await update.message.reply_text(
            genre_text,
            reply_markup=ReplyKeyboardMarkup([["❌ Отмена"]], resize_keyboard=True)
        )
        return EDIT_GENRES

    elif text == "⚙️ Настройки":
        settings_text = "⚙️ **НАСТРОЙКИ ОТОБРАЖЕНИЯ**\n\n"
        settings_text += f"BPM: {'✅' if channel.show_bpm else '❌'} /toggle_bpm\n"
        settings_text += f"Тональность: {'✅' if channel.show_key else '❌'} /toggle_key\n"
        settings_text += f"Жанр: {'✅' if channel.show_genre else '❌'} /toggle_genre\n"
        settings_text += f"Настроение: {'✅' if channel.show_mood else '❌'} /toggle_mood\n"
        settings_text += f"В стиле: {'✅' if channel.show_similar_artist else '❌'} /toggle_artist\n"
        settings_text += f"Коллабы: {'✅' if channel.show_collaborators else '❌'} /toggle_collab"
        await update.message.reply_text(settings_text, parse_mode=ParseMode.MARKDOWN)

    elif text == "📊 Статистика":
        beats = db.get_channel_beats(channel.channel_id)
        samples = db.get_channel_samples(channel.channel_id)
        orders = [o for o in db.orders.values() if o.channel_id == channel.channel_id and o.status == 'paid']
        revenue = sum(o.amount for o in orders)

        await update.message.reply_text(
            f"📊 **СТАТИСТИКА КАНАЛА**\n\n"
            f"Битов: {len(beats)}\n"
            f"Сэмплов: {len(samples)}\n"
            f"Продаж: {len(orders)}\n"
            f"Выручка: {revenue} ⭐",
            parse_mode=ParseMode.MARKDOWN
        )

    elif text == "📋 Мои товары":
        beats = db.get_channel_beats(channel.channel_id)
        samples = db.get_channel_samples(channel.channel_id)

        if not beats and not samples:
            await update.message.reply_text("📭 Пока нет товаров.")
        else:
            item_text = "📋 **ТВОИ ТОВАРЫ**\n\n"
            if beats:
                item_text += "**Биты:**\n"
                for beat in beats[-5:]:
                    status = "✅" if beat.is_active else "❌"
                    item_text += f"{status} `{beat.id}`: {beat.title} — {beat.purchases_count} продаж\n"
            if samples:
                item_text += "\n**Сэмплы:**\n"
                for sample in samples[-5:]:
                    status = "✅" if sample.is_active else "❌"
                    item_text += f"{status} `{sample.id}`: {sample.title} — {sample.purchases_count} продаж\n"
            await update.message.reply_text(item_text, parse_mode=ParseMode.MARKDOWN)

    elif text == "📄 Договоры":
        return await show_contracts_menu(update, context, channel)

    elif text == "🔐 Приватный канал":
        return await setup_private_channel(update, context, channel)

    elif text == "❌ Назад":
        context.user_data['current_channel'] = None
        return await start(update, context)

    return BEATMAKER_MENU


# ============ ДОБАВЛЕНИЕ БИТА (С КОЛЛАБАМИ) ============

async def add_beat_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "❌ Отмена":
        await update.message.reply_text("❌ Отменено.",
                                        reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True))
        return MAIN_MENU

    context.user_data['new_beat']['title'] = text
    await update.message.reply_text(
        "⚡ Введите BPM или 'пропустить':",
        reply_markup=ReplyKeyboardMarkup([["⏭️ Пропустить", "❌ Отмена"]], resize_keyboard=True)
    )
    return ADD_BEAT_BPM


async def add_beat_bpm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "❌ Отмена":
        await update.message.reply_text("❌ Отменено.",
                                        reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True))
        return MAIN_MENU

    if text == "⏭️ Пропустить":
        context.user_data['new_beat']['bpm'] = None
    else:
        try:
            bpm = int(text)
            context.user_data['new_beat']['bpm'] = bpm
        except:
            await update.message.reply_text("❌ Введи число или 'пропустить'")
            return ADD_BEAT_BPM

    await update.message.reply_text(
        "🎹 Введите тональность или 'пропустить':",
        reply_markup=ReplyKeyboardMarkup([["⏭️ Пропустить", "❌ Отмена"]], resize_keyboard=True)
    )
    return ADD_BEAT_KEY


async def add_beat_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "❌ Отмена":
        await update.message.reply_text("❌ Отменено.",
                                        reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True))
        return MAIN_MENU

    if text == "⏭️ Пропустить":
        context.user_data['new_beat']['key'] = None
    else:
        context.user_data['new_beat']['key'] = text

    current_channel = context.user_data.get('current_channel')
    channel = db.get_channel_by_username(current_channel)

    if channel and channel.show_genre:
        await update.message.reply_text(
            "🎼 Выберите жанр:",
            reply_markup=ReplyKeyboardMarkup(
                [[g] for g in channel.genres[:3]] + [["➕ Новый"], ["⏭️ Пропустить", "❌ Отмена"]],
                resize_keyboard=True
            )
        )
        return ADD_BEAT_GENRE
    else:
        context.user_data['new_beat']['genre'] = None
        return await ask_for_collab(update, context, channel)


async def add_beat_genre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    current_channel = context.user_data.get('current_channel')
    channel = db.get_channel_by_username(current_channel)

    if text == "❌ Отмена":
        await update.message.reply_text("❌ Отменено.",
                                        reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True))
        return MAIN_MENU

    if text == "⏭️ Пропустить":
        context.user_data['new_beat']['genre'] = None
    elif text == "➕ Новый":
        await update.message.reply_text("Введите название нового жанра:")
        return ADD_BEAT_GENRE
    elif text in channel.genres:
        context.user_data['new_beat']['genre'] = text
    else:
        # Добавляем новый жанр
        channel.genres.append(text)
        db.update_channel(channel.channel_username, genres=channel.genres)
        context.user_data['new_beat']['genre'] = text

    return await ask_for_collab(update, context, channel)


async def ask_for_collab(update: Update, context: ContextTypes.DEFAULT_TYPE, channel: BeatmakerChannel):
    if channel.subscription_tier == 'premium' and channel.show_collaborators:
        await update.message.reply_text(
            "🤝 Добавить коллабораторов?\n"
            "Отправь @username и процент через пробел.\n"
            "Например: @producer 50\n"
            "Или нажми 'пропустить'",
            reply_markup=ReplyKeyboardMarkup([["⏭️ Пропустить", "❌ Отмена"]], resize_keyboard=True)
        )
        return ADD_BEAT_COLLAB
    else:
        context.user_data['new_beat']['collaborators'] = []
        await update.message.reply_text(
            "🎵 Отправь MP3 файл (демо):",
            reply_markup=ReplyKeyboardMarkup([["❌ Отмена"]], resize_keyboard=True)
        )
        return ADD_BEAT_MP3


async def add_beat_collab(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "❌ Отмена":
        await update.message.reply_text("❌ Отменено.",
                                        reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True))
        return MAIN_MENU

    if text == "⏭️ Пропустить":
        context.user_data['new_beat']['collaborators'] = []
    else:
        try:
            parts = text.split()
            if len(parts) != 2:
                raise ValueError("Нужно 2 параметра")
            username = parts[0]
            percent = int(parts[1])

            if 'collaborators' not in context.user_data['new_beat']:
                context.user_data['new_beat']['collaborators'] = []

            context.user_data['new_beat']['collaborators'].append({
                'channel_username': username,
                'share_percent': percent
            })

            await update.message.reply_text(
                "✅ Коллаборатор добавлен!\n"
                "Добавить ещё? Отправь @username и процент\n"
                "Или нажми 'пропустить'",
                reply_markup=ReplyKeyboardMarkup([["⏭️ Пропустить", "❌ Отмена"]], resize_keyboard=True)
            )
            return ADD_BEAT_COLLAB
        except:
            await update.message.reply_text("❌ Неверный формат! Нужно: @username процент")
            return ADD_BEAT_COLLAB

    await update.message.reply_text(
        "🎵 Отправь MP3 файл (демо):",
        reply_markup=ReplyKeyboardMarkup([["❌ Отмена"]], resize_keyboard=True)
    )
    return ADD_BEAT_MP3


async def add_beat_mp3(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.audio:
        file_id = update.message.audio.file_id
    elif update.message.document and update.message.document.mime_type == 'audio/mpeg':
        file_id = update.message.document.file_id
    else:
        await update.message.reply_text("❌ Отправь MP3 файл!")
        return ADD_BEAT_MP3

    context.user_data['new_beat']['mp3_file_id'] = file_id

    await update.message.reply_text(
        "🖼️ Отправь обложку или 'пропустить':",
        reply_markup=ReplyKeyboardMarkup([["⏭️ Пропустить", "❌ Отмена"]], resize_keyboard=True)
    )
    return ADD_BEAT_COVER


async def add_beat_cover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "❌ Отмена":
        await update.message.reply_text("❌ Отменено.",
                                        reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True))
        return MAIN_MENU

    if text == "⏭️ Пропустить":
        context.user_data['new_beat']['cover_file_id'] = None
    elif update.message.photo:
        file_id = update.message.photo[-1].file_id
        context.user_data['new_beat']['cover_file_id'] = file_id
    else:
        await update.message.reply_text("❌ Отправь картинку или 'пропустить'!")
        return ADD_BEAT_COVER

    # Сохраняем бит
    beat_data = context.user_data['new_beat']
    beat_id = str(uuid.uuid4())[:8]

    collaborators = []
    for c in beat_data.get('collaborators', []):
        collaborators.append(CollabBeatmaker(**c))

    beat = Beat(
        id=beat_id,
        beatmaker_id=beat_data['beatmaker_id'],
        title=beat_data['title'],
        bpm=beat_data.get('bpm'),
        key=beat_data.get('key'),
        genre=beat_data.get('genre'),
        mood=beat_data.get('mood'),
        similar_artist=beat_data.get('similar_artist'),
        collaborators=collaborators,
        mp3_file_id=beat_data['mp3_file_id'],
        cover_file_id=beat_data.get('cover_file_id')
    )

    db.add_beat(beat)

    # Публикуем в канал
    current_channel = context.user_data.get('current_channel')
    channel = db.get_channel_by_username(current_channel)

    if channel:
        caption = format_beat_caption(beat, channel)
        keyboard = get_beat_keyboard(beat.id)

        try:
            if beat.cover_file_id:
                await context.bot.send_photo(
                    chat_id=channel.channel_id,
                    photo=beat.cover_file_id,
                    caption=caption,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=keyboard
                )
            else:
                await context.bot.send_message(
                    chat_id=channel.channel_id,
                    text=caption,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=keyboard
                )

            await context.bot.send_audio(
                chat_id=channel.channel_id,
                audio=beat.mp3_file_id,
                caption=f"🎧 {beat.title} (демо)"
            )

            await update.message.reply_text(
                f"✅ Бит добавлен и опубликован!",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True)
            )
        except Exception as e:
            logger.error(f"Ошибка публикации: {e}")
            await update.message.reply_text(
                f"✅ Бит сохранен, но не опубликован.",
                reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True)
            )

    context.user_data.pop('new_beat', None)
    return MAIN_MENU


# ============ ДОБАВЛЕНИЕ СЭМПЛА ============

async def add_sample_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "❌ Отмена":
        await update.message.reply_text("❌ Отменено.",
                                        reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True))
        return MAIN_MENU

    context.user_data['new_sample']['title'] = text
    await update.message.reply_text(
        "🎧 Отправь MP3 файл сэмпла:",
        reply_markup=ReplyKeyboardMarkup([["❌ Отмена"]], resize_keyboard=True)
    )
    return ADD_SAMPLE_MP3


async def add_sample_mp3(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.audio:
        file_id = update.message.audio.file_id
    elif update.message.document and update.message.document.mime_type == 'audio/mpeg':
        file_id = update.message.document.file_id
    else:
        await update.message.reply_text("❌ Отправь MP3 файл!")
        return ADD_SAMPLE_MP3

    context.user_data['new_sample']['mp3_file_id'] = file_id

    current_channel = context.user_data.get('current_channel')
    channel = db.get_channel_by_username(current_channel)
    default_price = channel.price_samples_default if channel else 30

    await update.message.reply_text(
        f"💰 Введите цену сэмпла в ⭐ (по умолчанию {default_price}):",
        reply_markup=ReplyKeyboardMarkup([["⏭️ Пропустить", "❌ Отмена"]], resize_keyboard=True)
    )
    return ADD_SAMPLE_PRICE


async def add_sample_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "❌ Отмена":
        await update.message.reply_text("❌ Отменено.",
                                        reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True))
        return MAIN_MENU

    current_channel = context.user_data.get('current_channel')
    channel = db.get_channel_by_username(current_channel)
    default_price = channel.price_samples_default if channel else 30

    if text == "⏭️ Пропустить":
        price = default_price
    else:
        try:
            price = int(text)
        except:
            await update.message.reply_text("❌ Введи число!")
            return ADD_SAMPLE_PRICE

    # Сохраняем сэмпл
    sample_data = context.user_data['new_sample']
    sample_id = str(uuid.uuid4())[:8]

    sample = Sample(
        id=sample_id,
        beatmaker_id=sample_data['beatmaker_id'],
        title=sample_data['title'],
        mp3_file_id=sample_data['mp3_file_id'],
        price=price
    )

    db.add_sample(sample)

    # Публикуем в канал
    if channel:
        caption = f"🎧 **НОВЫЙ СЭМПЛ**\n\n🎵 **{sample.title}**\n💰 Цена: {price} ⭐"
        keyboard = get_sample_keyboard(sample.id)

        try:
            await context.bot.send_message(
                chat_id=channel.channel_id,
                text=caption,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )

            await context.bot.send_audio(
                chat_id=channel.channel_id,
                audio=sample.mp3_file_id,
                caption=f"🎧 {sample.title}"
            )

            await update.message.reply_text(
                f"✅ Сэмпл добавлен и опубликован!",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True)
            )
        except Exception as e:
            logger.error(f"Ошибка публикации: {e}")
            await update.message.reply_text(
                f"✅ Сэмпл сохранен.",
                reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True)
            )

    context.user_data.pop('new_sample', None)
    return MAIN_MENU


# ============ ПРИВАТНЫЙ КАНАЛ ============

async def setup_private_channel(update: Update, context: ContextTypes.DEFAULT_TYPE, channel: BeatmakerChannel):
    if channel.subscription_tier != 'premium':
        await update.message.reply_text(
            "❌ Приватные каналы доступны только в Премиум-тарифе!",
            parse_mode=ParseMode.MARKDOWN
        )
        return BEATMAKER_MENU

    if channel.private_channel:
        text = f"🔐 **ПРИВАТНЫЙ КАНАЛ**\n\n"
        text += f"Канал: {channel.private_channel.channel_username}\n"
        text += f"Цена: {channel.private_channel.price_month} ⭐/мес\n"
        text += f"Ссылка: {channel.private_channel.invite_link}\n\n"
        text += "Что хочешь сделать?"

        keyboard = [
            ["💰 Изменить цену", "🔄 Обновить ссылку"],
            ["📊 Подписчики", "❌ Назад"]
        ]
    else:
        text = "🔐 **НАСТРОЙКА ПРИВАТНОГО КАНАЛА**\n\n"
        text += "Отправь @username приватного канала и цену в формате:\n"
        text += "`@privatechannel 150`\n\n"
        text += "Канал должен быть создан заранее, а бот добавлен администратором!"

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardMarkup(keyboard if channel.private_channel else [["❌ Назад"]], resize_keyboard=True)
    )
    return PRIVATE_CHANNEL_SETUP


async def private_channel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    current_channel = context.user_data.get('current_channel')
    channel = db.get_channel_by_username(current_channel)

    if text == "❌ Назад":
        return await show_beatmaker_menu(update, context, channel)

    if channel.private_channel:
        if text.startswith("💰 Изменить цену"):
            await update.message.reply_text("Введите новую цену в ⭐:")
            context.user_data['awaiting_private_price'] = True
        elif text.startswith("🔄 Обновить ссылку"):
            await update.message.reply_text("Отправь новую ссылку-приглашение:")
            context.user_data['awaiting_private_link'] = True
        elif text.startswith("📊 Подписчики"):
            # Показываем список подписчиков
            subscribers = []
            for access in db.private_access.values():
                if access.beatmaker_id == channel.channel_id:
                    user = db.get_user(access.user_id)
                    expires = datetime.fromisoformat(access.expires_at).strftime("%d.%m.%Y")
                    subscribers.append(f"• {user.first_name}: до {expires}")

            if subscribers:
                await update.message.reply_text(
                    "📊 **ПОДПИСЧИКИ ПРИВАТНОГО КАНАЛА**\n\n" + "\n".join(subscribers),
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text("📭 Пока нет подписчиков.")
    else:
        # Настройка нового приватного канала
        try:
            parts = text.split()
            if len(parts) != 2:
                raise ValueError("Нужно 2 параметра")

            private_username = parts[0]
            price = int(parts[1])

            if not private_username.startswith('@'):
                private_username = '@' + private_username

            # Создаем пригласительную ссылку (надо получить от пользователя)
            await update.message.reply_text(
                f"✅ Канал {private_username} выбран.\n"
                f"Цена: {price} ⭐/мес\n\n"
                f"Теперь отправь ссылку-приглашение в этот канал.\n"
                f"(Бот должен быть администратором канала!)"
            )
            context.user_data['private_setup'] = {
                'username': private_username,
                'price': price
            }
            context.user_data['awaiting_private_link'] = True

        except:
            await update.message.reply_text("❌ Неверный формат! Нужно: @privatechannel 150")

    return PRIVATE_CHANNEL_SETUP


async def private_channel_link_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_private_link'):
        return PRIVATE_CHANNEL_SETUP

    link = update.message.text.strip()
    current_channel = context.user_data.get('current_channel')
    channel = db.get_channel_by_username(current_channel)

    if 'private_setup' in context.user_data:
        # Новый канал
        setup = context.user_data['private_setup']
        db.set_private_channel(
            channel_id=channel.channel_id,
            private_id=setup['username'],
            private_username=setup['username'],
            invite_link=link,
            price_month=setup['price']
        )
        await update.message.reply_text("✅ Приватный канал настроен!")
        context.user_data.pop('private_setup')
    else:
        # Обновление ссылки
        if channel.private_channel:
            channel.private_channel.invite_link = link
            db._save("channels.json", db.channels)
            await update.message.reply_text("✅ Ссылка обновлена!")

    context.user_data['awaiting_private_link'] = False
    return await show_beatmaker_menu(update, context, channel)


# ============ СИСТЕМА ДОГОВОРОВ ============

async def show_contracts_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, channel: BeatmakerChannel):
    orders = db.get_channel_orders(channel.channel_id)

    text = f"📄 **УПРАВЛЕНИЕ ДОГОВОРАМИ**\n\n"
    text += f"📝 Шаблон договора:\n`{channel.contract_template[:100]}...`\n\n"
    text += f"📋 **ЗАПРОСЫ НА ПОДПИСАНИЕ:**\n"

    pending_orders = [o for o in orders if o.contract_sent and not o.contract_signed]
    if pending_orders:
        for order in pending_orders:
            if order.item_type == 'beat':
                beat = db.get_beat(order.item_id)
                user = db.get_user(order.user_id)
                if beat:
                    text += f"• {beat.title} — {user.first_name}\n"
                    text += f"  /sign_{order.id} — отметить подписанным\n"
    else:
        text += "• Нет ожидающих запросов\n"

    text += "\n⚙️ **Управление:**\n"
    text += "/edit_template — редактировать шаблон\n"
    text += "/contract_stats — статистика по договорам"

    keyboard = [["❌ Назад"]]

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return CONTRACT_MENU


# ============ ПОКУПКИ И ПЛАТЕЖИ ============

async def beat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.split('_')
    action = data[1]

    if action == 'beat':
        beat_id = data[2]
        purchase_type = data[3]

        beat = db.get_beat(beat_id)
        if not beat or not beat.is_active:
            await query.edit_message_text("❌ Бит не доступен.")
            return

        if purchase_type == 'wav':
            price = beat.price_wav
        elif purchase_type == 'exclusive':
            price = beat.price_exclusive
        elif purchase_type == 'stems':
            price = beat.price_stems
        else:
            return

        user_id = update.effective_user.id
        order = db.create_order(beat.beatmaker_id, 'beat', beat_id, user_id, price, purchase_type)

        await query.edit_message_text(
            f"💰 **Покупка: {beat.title}**\n\n"
            f"Тип: {purchase_type}\n"
            f"Цена: {price} ⭐",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(f"💎 Оплатить {price} ⭐", callback_data=f"pay_{order.id}")
            ]])
        )

    elif action == 'sample':
        sample_id = data[2]
        sample = db.get_sample(sample_id)
        if not sample:
            await query.edit_message_text("❌ Сэмпл не найден.")
            return

        user_id = update.effective_user.id
        order = db.create_order(sample.beatmaker_id, 'sample', sample_id, user_id, sample.price, None)

        await query.edit_message_text(
            f"💰 **Покупка сэмпла: {sample.title}**\n\n"
            f"Цена: {sample.price} ⭐",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(f"💎 Оплатить {sample.price} ⭐", callback_data=f"pay_{order.id}")
            ]])
        )

    elif action == 'private':
        channel_username = data[2]
        months = int(data[3])

        channel = db.get_channel_by_username(channel_username)
        if not channel or not channel.private_channel:
            await query.edit_message_text("❌ Приватный канал не найден.")
            return

        price = channel.private_channel.price_month * months
        user_id = update.effective_user.id

        order = db.create_order(channel.channel_id, 'private', channel_username, user_id, price, f"{months} мес")

        await query.edit_message_text(
            f"🔐 **Доступ в приватный канал**\n\n"
            f"Канал: {channel_username}\n"
            f"Срок: {months} мес\n"
            f"Цена: {price} ⭐",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(f"💎 Оплатить {price} ⭐", callback_data=f"pay_{order.id}")
            ]])
        )

    elif action == 'info' and data[0] == 'info':
        beat_id = data[2]
        beat = db.get_beat(beat_id)
        if not beat:
            await query.edit_message_text("❌ Бит не найден.")
            return

        info_text = f"""
ℹ️ **ИНФОРМАЦИЯ О БИТЕ**

🎵 **{beat.title}**
⚡ BPM: {beat.bpm or 'не указан'}
🎹 Тональность: {beat.key or 'не указана'}
🎼 Жанр: {beat.genre or 'не указан'}

💰 **Цены:**
• WAV: {beat.price_wav} ⭐
• Эксклюзив: {beat.price_exclusive} ⭐
• Стэмзы: {beat.price_stems} ⭐
        """

        await query.edit_message_text(
            text=info_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_beat_keyboard(beat.id)
        )


async def pay_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    order_id = query.data.split('_')[1]
    order = db.get_order(order_id)

    if not order:
        await query.edit_message_text("❌ Заказ не найден.")
        return

    await context.bot.send_invoice(
        chat_id=update.effective_chat.id,
        title="Оплата заказа",
        description=f"Заказ #{order_id}",
        payload=order.id,
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Товар", amount=order.amount)]
    )


async def pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    order_id = query.invoice_payload
    order = db.get_order(order_id)

    if order:
        if order.item_type == 'beat':
            beat = db.get_beat(order.item_id)
            if not beat or not beat.is_active:
                await query.answer(ok=False, error_message="Товар больше не доступен")
                return
    else:
        sub_order = db.get_subscription_order(order_id)
        if not sub_order:
            await query.answer(ok=False, error_message="Заказ не найден")
            return

    await query.answer(ok=True)


async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment = update.message.successful_payment
    payload = payment.invoice_payload

    # Проверяем заказ
    order = db.get_order(payload)
    if order:
        db.update_order_status(payload, 'paid')

        if order.item_type == 'beat':
            beat = db.get_beat(order.item_id)
            beat.purchases_count += 1
            db.update_beat(beat.id, purchases_count=beat.purchases_count)

            await update.message.reply_text(
                f"✅ **Оплата прошла!**\n\n"
                f"Сейчас отправлю файлы и договор...",
                parse_mode=ParseMode.MARKDOWN
            )

            # Отправляем файл
            await update.message.reply_document(
                document=beat.mp3_file_id,
                caption=f"✅ {beat.title} ({order.purchase_type})"
            )

            # Генерируем договор
            channel = db.get_channel(order.channel_id)
            buyer = db.get_user(order.user_id)

            if channel:
                contract_text = generate_contract(beat, order, buyer, channel)
                await update.message.reply_text(
                    f"📄 **ДОГОВОР**\n\n{contract_text}\n\n"
                    f"Пожалуйста, подпиши и отправь скан обратно.",
                    parse_mode=ParseMode.MARKDOWN
                )

                db.update_order(payload, contract_sent=True)

                # Уведомляем битмейкера
                try:
                    await context.bot.send_message(
                        chat_id=channel.user_id,
                        text=f"📄 **НОВЫЙ ЗАПРОС НА ДОГОВОР!**\n\n"
                             f"Бит: {beat.title}\n"
                             f"Покупатель: {buyer.first_name}\n"
                             f"ID заказа: {order.id}\n\n"
                             f"/sign_{order.id} — отметить подписанным",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except:
                    pass

        elif order.item_type == 'sample':
            sample = db.get_sample(order.item_id)
            sample.purchases_count += 1
            db.update_sample(sample.id, purchases_count=sample.purchases_count)

            await update.message.reply_text("✅ Оплата прошла! Отправляю сэмпл...")
            await update.message.reply_document(
                document=sample.mp3_file_id,
                caption=f"✅ {sample.title}"
            )

        elif order.item_type == 'private':
            channel = db.get_channel(order.channel_id)
            if channel and channel.private_channel:
                months = int(order.purchase_type.split()[0])
                db.grant_private_access(
                    channel_id=channel.channel_id,
                    user_id=order.user_id,
                    private_username=channel.private_channel.channel_username,
                    months=months
                )

                await update.message.reply_text(
                    f"✅ Доступ в приватный канал открыт!\n\n"
                    f"Ссылка: {channel.private_channel.invite_link}\n\n"
                    f"Доступ действует {months} мес.",
                    parse_mode=ParseMode.MARKDOWN
                )

        db.update_order_status(payload, 'delivered')

    else:
        # Обработка подписки
        db.activate_subscription(payload)
        await update.message.reply_text(
            f"✅ **Подписка активирована!**",
            parse_mode=ParseMode.MARKDOWN
        )


# ============ MAIN ============

def main():
    application = Application.builder().token(BOT_TOKEN).build()

    # Команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("catalog", catalog))
    application.add_handler(CommandHandler("my_purchases", my_purchases))
    application.add_handler(CommandHandler("subscribe", subscribe))
    application.add_handler(CommandHandler("admin", super_admin_panel))

    # Команды для договоров
    application.add_handler(MessageHandler(filters.Regex(r'^/sign_'), lambda u, c: None))  # TODO: реализовать

    # Инлайн-колбэки
    application.add_handler(CallbackQueryHandler(subscription_callback, pattern="^sub_"))
    application.add_handler(CallbackQueryHandler(beat_callback, pattern="^(buy_|info_)"))
    application.add_handler(CallbackQueryHandler(pay_callback, pattern="^pay_"))

    # Платежи
    application.add_handler(PreCheckoutQueryHandler(pre_checkout))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))

    # Job для проверки подписок
    job_queue = application.job_queue
    job_queue.run_repeating(check_subscriptions, interval=timedelta(hours=24), first=10)

    # ConversationHandler
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex("^(👑 Панель суперадмина)$"), super_admin_panel),
        ],
        states={
            MAIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, start)],
            SUPER_ADMIN_MENU: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    lambda u, c: add_channel_handler(u, c) if c.user_data.get(
                        'expecting_new_channel') else super_admin_menu_handler(u, c)
                )
            ],
            EDIT_SUBSCRIPTION_PRICES: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_price_settings)],
            MY_CHANNELS_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, my_channels_handler)],
            BEATMAKER_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, beatmaker_menu_handler)],
            ADD_BEAT_TITLE: [MessageHandler(filters.TEXT, add_beat_title)],
            ADD_BEAT_BPM: [MessageHandler(filters.TEXT, add_beat_bpm)],
            ADD_BEAT_KEY: [MessageHandler(filters.TEXT, add_beat_key)],
            ADD_BEAT_GENRE: [MessageHandler(filters.TEXT, add_beat_genre)],
            ADD_BEAT_COLLAB: [MessageHandler(filters.TEXT, add_beat_collab)],
            ADD_BEAT_MP3: [MessageHandler(filters.AUDIO | filters.Document.ALL, add_beat_mp3)],
            ADD_BEAT_COVER: [MessageHandler(filters.PHOTO | filters.TEXT, add_beat_cover)],
            ADD_SAMPLE_TITLE: [MessageHandler(filters.TEXT, add_sample_title)],
            ADD_SAMPLE_MP3: [MessageHandler(filters.AUDIO | filters.Document.ALL, add_sample_mp3)],
            ADD_SAMPLE_PRICE: [MessageHandler(filters.TEXT, add_sample_price)],
            SUBSCRIPTION_CONFIRM: [MessageHandler(filters.TEXT, subscription_confirm)],
            PRIVATE_CHANNEL_SETUP: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    lambda u, c: private_channel_link_handler(u, c) if c.user_data.get(
                        'awaiting_private_link') else private_channel_handler(u, c)
                )
            ],
            CONTRACT_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: None)],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True
    )

    application.add_handler(conv_handler)

    print("🚀 БИТМЕЙКЕР-ПЛАТФОРМА v4.0 ЗАПУЩЕНА!")
    print(f"👑 Суперадмин ID: {SUPER_ADMIN_ID}")
    print(f"📅 Планировщик уведомлений активен")
    print(f"🔐 Поддержка приватных каналов, коллабов, сэмплов")
    print(f"⚙️ Цены подписок настраиваются в панели")
    print(f"✅ Суперадмин может управлять своими каналами как обычный битмейкер")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()