import logging
import json
import os
import csv
import asyncio
import aiohttp
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, CallbackContext, ConversationHandler
from telegram.constants import ParseMode
from telegram.error import NetworkError, TelegramError

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Konuşma durumları
AWAITING_NOTE, AWAITING_USER_ID, AWAITING_BROADCAST, AWAITING_POINTS_AMOUNT, AWAITING_SET_POINTS, AWAITING_PRODUCT_NAME, AWAITING_PRODUCT_POINTS, AWAITING_PRODUCT_DESC = range(8)

# Emojiler
EMOJIS = {
    'shop': '🛍️', 'referral': '👥', 'points': '⭐', 'balance': '💰', 'gift': '🎁',
    'warning': '⚠️', 'success': '✅', 'error': '❌', 'info': 'ℹ️', 'star': '🌟',
    'trophy': '🏆', 'coin': '🪙', 'package': '📦', 'rocket': '🚀', 'fire': '🔥',
    'crown': '👑', 'back': '🔙', 'check': '✔️', 'cross': '❌', 'lock': '🔒',
    'unlock': '🔓', 'bell': '🔔', 'user': '👤', 'users': '👥', 'chart': '📊',
    'netflix': '🎬', 'exxen': '🎭', 'supercell': '🎮', 'yemeksepeti': '🍔',
    'trendyol': '👗', 'random': '🎲', 'link': '🔗', 'calendar': '📅', 'clock': '⏰',
    'money': '💵', 'card': '💳', 'bank': '🏦', 'home': '🏠', 'gear': '⚙️',
    'download': '📥', 'stats': '📈', 'search': '🔍', 'edit': '✏️', 'trash': '🗑️',
    'refresh': '🔄', 'connection': '📡', 'wifi': '📶', 'cloud': '☁️'
}

class ReferralBot:
    def __init__(self, token: str):
        self.token = token
        
        # Proxy/Network ayarları
        self.request_kwargs = {
            'connect_timeout': 30.0,
            'read_timeout': 30.0,
            'write_timeout': 30.0,
            'pool_timeout': 30.0,
        }
        
        # Proxy kullanmak isterseniz (opsiyonel)
        # self.request_kwargs['proxy_url'] = 'http://proxy_url:port'
        # self.request_kwargs['proxy'] = {'http': 'http://proxy_url:port', 'https': 'https://proxy_url:port'}
        
        try:
            self.application = Application.builder()\
                .token(token)\
                .connect_timeout(30.0)\
                .read_timeout(30.0)\
                .write_timeout(30.0)\
                .pool_timeout(30.0)\
                .get_updates_read_timeout(30.0)\
                .build()
        except Exception as e:
            logger.error(f"Application oluşturma hatası: {e}")
            raise
        
        # Veri dosyaları
        self.data_dir = "bot_data"
        self.reports_dir = "reports"
        self.backup_dir = "backups"
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.reports_dir, exist_ok=True)
        os.makedirs(self.backup_dir, exist_ok=True)
        
        self.users_file = os.path.join(self.data_dir, "users.json")
        self.orders_file = os.path.join(self.data_dir, "orders.json")
        self.products_file = os.path.join(self.data_dir, "products.json")
        
        # Verileri yükle
        self.users = self.load_json(self.users_file, {})
        self.orders = self.load_json(self.orders_file, {})
        self.products = self.load_json(self.products_file, [
            {'id': 1, 'name': 'Netflix Hit/Log', 'points': 2, 'desc': 'Netflix hesabı', 'emoji': EMOJIS['netflix']},
            {'id': 2, 'name': 'Exxen Hit', 'points': 2, 'desc': 'Exxen premium', 'emoji': EMOJIS['exxen']},
            {'id': 3, 'name': 'Supercell Random Hit', 'points': 4, 'desc': 'Supercell hesapları', 'emoji': EMOJIS['supercell']},
            {'id': 4, 'name': 'Yemeksepeti Random Hit', 'points': 3, 'desc': 'Yemeksepeti hesabı', 'emoji': EMOJIS['yemeksepeti']},
            {'id': 5, 'name': 'Trendyol Go', 'points': 5, 'desc': 'Trendyol Go üyeliği', 'emoji': EMOJIS['trendyol']},
            {'id': 6, 'name': '100x Random Hits', 'points': 10, 'desc': '100 adet çeşitli hit', 'emoji': EMOJIS['random']}
        ])
        
        # Ayarlar
        self.admin_id = 8280345878  # Telegram ID'niz
        self.channel_username = "kusursuzarsiv"
        self.channel_link = f"https://t.me/{self.channel_username}"
        
        # Retry mekanizması için
        self.retry_count = 0
        self.max_retries = 3
        
        self.setup_handlers()
        self.create_backup()
    
    def load_json(self, filename, default):
        """JSON dosyasını yükle"""
        try:
            if os.path.exists(filename):
                with open(filename, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"JSON yükleme hatası {filename}: {e}")
            self.create_backup()  # Hata durumunda backup al
        return default
    
    def save_json(self, filename, data):
        """JSON dosyasını kaydet"""
        try:
            # Önce backup al
            if os.path.exists(filename):
                backup_file = os.path.join(self.backup_dir, f"{os.path.basename(filename)}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
                try:
                    import shutil
                    shutil.copy2(filename, backup_file)
                except:
                    pass
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"JSON kaydetme hatası {filename}: {e}")
            return False
    
    def create_backup(self):
        """Veritabanı yedeği oluştur"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_files = []
            
            for filepath, data, name in [
                (self.users_file, self.users, "users"),
                (self.orders_file, self.orders, "orders"),
                (self.products_file, self.products, "products")
            ]:
                backup_file = os.path.join(self.backup_dir, f"{name}_backup_{timestamp}.json")
                with open(backup_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                backup_files.append(backup_file)
            
            # Eski backup'ları temizle (7 günden eski)
            self.clean_old_backups()
            
            logger.info(f"Backup oluşturuldu: {backup_files}")
            return True
        except Exception as e:
            logger.error(f"Backup oluşturma hatası: {e}")
            return False
    
    def clean_old_backups(self, days=7):
        """Eski backup'ları temizle"""
        try:
            cutoff_date = datetime.now() - timedelta(days=days)
            for filename in os.listdir(self.backup_dir):
                filepath = os.path.join(self.backup_dir, filename)
                if os.path.isfile(filepath):
                    file_time = datetime.fromtimestamp(os.path.getmtime(filepath))
                    if file_time < cutoff_date:
                        os.remove(filepath)
                        logger.info(f"Eski backup silindi: {filename}")
        except Exception as e:
            logger.error(f"Backup temizleme hatası: {e}")
    
    def setup_handlers(self):
        """Handler'ları kur"""
        # Ana handler'lar
        self.application.add_handler(CommandHandler('start', self.start))
        self.application.add_handler(CommandHandler('admin', self.admin_panel_command))
        self.application.add_handler(CommandHandler('stats', self.show_stats_command))
        self.application.add_handler(CommandHandler('broadcast', self.broadcast_command))
        self.application.add_handler(CommandHandler('addpoints', self.add_points_command))
        self.application.add_handler(CommandHandler('setpoints', self.set_points_command))
        self.application.add_handler(CommandHandler('addproduct', self.add_product_command))
        self.application.add_handler(CommandHandler('report', self.generate_report_command))
        self.application.add_handler(CommandHandler('export', self.export_data_command))
        self.application.add_handler(CommandHandler('backup', self.create_backup_command))
        self.application.add_handler(CommandHandler('ping', self.ping_command))
        
        # Callback handler
        self.application.add_handler(CallbackQueryHandler(self.button_handler))
        
        # Message handler
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        # Error handler
        self.application.add_error_handler(self.error_handler)
    
    async def error_handler(self, update: Update, context: CallbackContext):
        """Global error handler"""
        try:
            logger.error(f"Exception while handling an update: {context.error}", exc_info=context.error)
            
            # Network hataları için retry
            if isinstance(context.error, NetworkError):
                self.retry_count += 1
                if self.retry_count <= self.max_retries:
                    logger.info(f"Network hatası, {self.retry_count}. deneme...")
                    await asyncio.sleep(2 ** self.retry_count)  # Exponential backoff
                else:
                    logger.error(f"Maksimum retry sayısına ulaşıldı: {self.max_retries}")
                    self.retry_count = 0
            else:
                self.retry_count = 0
            
            # Kullanıcıya hata mesajı gönder
            if update and update.effective_user:
                try:
                    await update.effective_message.reply_text(
                        f"{EMOJIS['error']} Bir hata oluştu. Lütfen daha sonra tekrar deneyin.",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except:
                    pass
        except Exception as e:
            logger.error(f"Error handler'da hata: {e}")
    
    async def safe_send_message(self, chat_id, text, **kwargs):
        """Güvenli mesaj gönderme fonksiyonu"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                await self.application.bot.send_message(chat_id=chat_id, text=text, **kwargs)
                return True
            except NetworkError as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff
                    logger.warning(f"Network hatası, {wait_time}s sonra tekrar denenecek...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Mesaj gönderilemedi: {e}")
                    return False
            except Exception as e:
                logger.error(f"Mesaj gönderme hatası: {e}")
                return False
        return False
    
    def is_admin(self, user_id: int) -> bool:
        """Admin kontrolü"""
        return user_id == self.admin_id or self.users.get(str(user_id), {}).get('is_admin', False)
    
    async def check_channel(self, user_id: int, context: CallbackContext) -> bool:
        """Kanal kontrolü"""
        try:
            member = await context.bot.get_chat_member(f"@{self.channel_username}", user_id)
            return member.status in ['member', 'administrator', 'creator']
        except Exception as e:
            logger.error(f"Kanal kontrol hatası: {e}")
            return False
    
    async def start(self, update: Update, context: CallbackContext):
        """Başlangıç komutu"""
        try:
            user_id = update.effective_user.id
            username = update.effective_user.username or ""
            first_name = update.effective_user.first_name or "Kullanıcı"
            
            is_admin = self.is_admin(user_id)
            
            # Kullanıcı kaydı
            if str(user_id) not in self.users:
                initial_points = 999999 if is_admin else 0
                
                self.users[str(user_id)] = {
                    'username': username,
                    'first_name': first_name,
                    'referral_code': str(user_id)[-6:],
                    'points': initial_points,
                    'referrals': [],
                    'referrer': None,
                    'total_earned': 0,
                    'join_date': datetime.now().isoformat(),
                    'channel_checked': False,
                    'is_admin': is_admin,
                    'last_active': datetime.now().isoformat()
                }
                self.save_json(self.users_file, self.users)
                logger.info(f"Yeni kullanıcı: {user_id} - Admin: {is_admin}")
            else:
                # Son aktif zamanını güncelle
                self.users[str(user_id)]['last_active'] = datetime.now().isoformat()
                self.save_json(self.users_file, self.users)
            
            # Referans kontrolü
            if context.args:
                ref_code = context.args[0]
                await self.handle_referral(update, context, ref_code)
            
            # Admin ise direkt ana menü
            if is_admin:
                await self.show_main_menu(update, context)
                return
            
            # Normal kullanıcı için kanal kontrolü
            in_channel = await self.check_channel(user_id, context)
            
            if not in_channel:
                await self.show_join_message(update, context)
            else:
                self.users[str(user_id)]['channel_checked'] = True
                self.save_json(self.users_file, self.users)
                await self.show_main_menu(update, context)
                
        except Exception as e:
            logger.error(f"Start komutu hatası: {e}")
            await update.message.reply_text(
                f"{EMOJIS['error']} Bir hata oluştu. Lütfen tekrar deneyin.",
                parse_mode=ParseMode.MARKDOWN
            )
    
    async def show_join_message(self, update: Update, context: CallbackContext):
        """Kanal katılma mesajı"""
        keyboard = [
            [InlineKeyboardButton(f"{EMOJIS['users']} KANALA KATIL", url=self.channel_link)],
            [InlineKeyboardButton(f"{EMOJIS['check']} KATILDIĞIMI KONTROL ET", callback_data='check_channel')]
        ]
        
        msg = (
            f"{EMOJIS['lock']} *KANAL ÜYELİĞİ GEREKLİ!*\n\n"
            f"{EMOJIS['info']} Botu kullanmak için kanalımıza katılın:\n\n"
            f"{EMOJIS['link']} *Kanal:* @{self.channel_username}\n\n"
            f"1. Yukarıdaki butona tıklayın\n"
            f"2. Kanala katılın\n"
            f"3. 'Katıldığımı Kontrol Et' butonuna basın"
        )
        
        try:
            if update.callback_query:
                await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Join mesajı gönderme hatası: {e}")
    
    async def show_main_menu(self, update: Update, context: CallbackContext):
        """Ana menüyü göster"""
        try:
            user_id = update.effective_user.id
            user = self.users.get(str(user_id), {})
            points = user.get('points', 0)
            referrals = len(user.get('referrals', []))
            is_admin = self.is_admin(user_id)
            
            # Referans linki
            bot_username = context.bot.username
            ref_code = user.get('referral_code', str(user_id)[-6:])
            ref_link = f"https://t.me/{bot_username}?start={ref_code}"
            
            points_display = "SINIRSIZ" if is_admin else points
            
            keyboard = [
                [InlineKeyboardButton(f"{EMOJIS['shop']} ÜRÜNLER", callback_data='shop'),
                 InlineKeyboardButton(f"{EMOJIS['referral']} REFERANS", callback_data='ref_info')],
                [InlineKeyboardButton(f"{EMOJIS['points']} PUAN: {points_display}", callback_data='balance'),
                 InlineKeyboardButton(f"{EMOJIS['users']} DAVET: {referrals}", callback_data='ref_info')],
                [InlineKeyboardButton(f"{EMOJIS['chart']} LİDERLİK", callback_data='leaderboard'),
                 InlineKeyboardButton(f"{EMOJIS['info']} YARDIM", callback_data='help')],
                [InlineKeyboardButton(f"{EMOJIS['users']} KANALA GİT", url=self.channel_link),
                 InlineKeyboardButton(f"{EMOJIS['check']} KONTROL ET", callback_data='check_channel')]
            ]
            
            if is_admin:
                keyboard.append([InlineKeyboardButton(f"{EMOJIS['crown']} ADMIN PANEL", callback_data='admin_panel')])
            
            admin_tag = f"\n{EMOJIS['crown']} *Admin Modu Aktif*" if is_admin else ""
            
            msg = (
                f"{EMOJIS['rocket']} *REFERANS BOTUNA HOŞ GELDİN!*{admin_tag}\n\n"
                f"{EMOJIS['user']} *Kullanıcı:* {user.get('first_name', 'Kullanıcı')}\n"
                f"{EMOJIS['star']} *Puanınız:* {points_display}\n"
                f"{EMOJIS['users']} *Davet Sayınız:* {referrals} kişi\n"
                f"{EMOJIS['link']} *Referans Linkin:*\n`{ref_link}`\n\n"
                f"{EMOJIS['fire']} *1 DAVET = 1 PUAN*\n\n"
                f"{EMOJIS['gift']} *Ürünlerimiz:*\n"
            )
            
            for product in self.products[:3]:
                msg += f"{product['emoji']} {product['name']} - {product['points']}⭐\n"
            
            if len(self.products) > 3:
                msg += f"{EMOJIS['shop']} Daha fazlası için ÜRÜNLER butonuna basın\n"
            
            if update.callback_query:
                await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
                
        except Exception as e:
            logger.error(f"Ana menü gösterim hatası: {e}")
            await update.message.reply_text(
                f"{EMOJIS['error']} Menü yüklenirken hata oluştu.",
                parse_mode=ParseMode.MARKDOWN
            )
    
    async def handle_referral(self, update: Update, context: CallbackContext, ref_code: str):
        """Referans işleme"""
        try:
            user_id = update.effective_user.id
            
            if str(user_id)[-6:] == ref_code:
                return
            
            if self.users.get(str(user_id), {}).get('referrer'):
                return
            
            referrer_id = None
            for uid, data in self.users.items():
                if data.get('referral_code') == ref_code:
                    referrer_id = int(uid)
                    break
            
            if referrer_id and referrer_id != user_id:
                self.users[str(user_id)]['referrer'] = referrer_id
                
                if str(referrer_id) in self.users:
                    if 'referrals' not in self.users[str(referrer_id)]:
                        self.users[str(referrer_id)]['referrals'] = []
                    
                    if user_id not in self.users[str(referrer_id)]['referrals']:
                        self.users[str(referrer_id)]['referrals'].append(user_id)
                        
                        # Admin değilse puan ver
                        if not self.users[str(referrer_id)].get('is_admin', False):
                            self.users[str(referrer_id)]['points'] = self.users[str(referrer_id)].get('points', 0) + 1
                            self.users[str(referrer_id)]['total_earned'] = self.users[str(referrer_id)].get('total_earned', 0) + 1
                            self.save_json(self.users_file, self.users)
                        
                        # Bildirim gönder
                        try:
                            await self.safe_send_message(
                                chat_id=referrer_id,
                                text=f"{EMOJIS['gift']} *YENİ REFERANS!*\n\n@{update.effective_user.username or 'Kullanıcı'} senin referansınla katıldı!\n{EMOJIS['star']} +1 puan kazandın!\nToplam: {self.users[str(referrer_id)]['points']} puan",
                                parse_mode=ParseMode.MARKDOWN
                            )
                        except Exception as e:
                            logger.error(f"Referans bildirimi gönderilemedi: {e}")
                            
        except Exception as e:
            logger.error(f"Referans işleme hatası: {e}")
    
    async def button_handler(self, update: Update, context: CallbackContext):
        """Buton tıklama handler'ı"""
        query = update.callback_query
        await query.answer()
        
        try:
            data = query.data
            
            if data == 'back_to_menu':
                await self.show_main_menu(update, context)
            
            elif data == 'check_channel':
                user_id = update.effective_user.id
                
                if self.is_admin(user_id):
                    await query.answer("✅ Adminsiniz, direkt geçebilirsiniz!")
                    await self.show_main_menu(update, context)
                    return
                
                in_channel = await self.check_channel(user_id, context)
                
                if in_channel:
                    self.users[str(user_id)]['channel_checked'] = True
                    self.save_json(self.users_file, self.users)
                    await query.answer("✅ Kanal üyeliğiniz onaylandı!")
                    await self.show_main_menu(update, context)
                else:
                    await query.answer("❌ Henüz kanala katılmadınız!")
            
            elif data == 'shop':
                await self.show_shop(update, context)
            
            elif data.startswith('buy_'):
                idx = int(data.split('_')[1])
                await self.buy_product(update, context, idx)
            
            elif data.startswith('confirm_'):
                idx = int(data.split('_')[1])
                await self.confirm_purchase(update, context, idx)
            
            elif data == 'ref_info':
                await self.show_ref_info(update, context)
            
            elif data == 'balance':
                user_id = update.effective_user.id
                is_admin = self.is_admin(user_id)
                points = self.users.get(str(user_id), {}).get('points', 0)
                points_display = "SINIRSIZ" if is_admin else points
                await query.answer(f"💰 Puanınız: {points_display}")
            
            elif data == 'leaderboard':
                await self.show_leaderboard(update, context)
            
            elif data == 'help':
                await self.show_help(update, context)
            
            elif data == 'admin_panel':
                await self.show_admin_panel(update, context)
            
            elif data.startswith('approve_'):
                order_id = data.split('_')[1]
                await self.approve_order(update, context, order_id)
            
            elif data.startswith('reject_'):
                order_id = data.split('_')[1]
                await self.reject_order(update, context, order_id)
            
            elif data == 'admin_stats':
                await self.show_admin_stats(update, context)
            
            elif data == 'admin_users':
                await self.show_admin_users(update, context)
            
            elif data == 'admin_orders':
                await self.show_admin_orders(update, context)
            
            elif data == 'admin_add_points':
                await self.start_add_points(update, context)
            
            elif data == 'admin_broadcast':
                await self.start_broadcast_input(update, context)
            
            elif data == 'admin_export':
                await self.export_data(update, context)
            
            elif data == 'admin_report':
                await self.generate_report(update, context)
            
            elif data == 'admin_add_product':
                await self.start_add_product(update, context)
            
            elif data == 'admin_backup':
                await self.create_backup_command(update, context)
            
            elif data == 'admin_cleanup':
                await self.cleanup_data(update, context)
            
            elif data == 'refresh_menu':
                await self.show_main_menu(update, context)
                
        except Exception as e:
            logger.error(f"Buton işleme hatası: {e}")
            await query.answer("❌ Hata oluştu!")
            await self.show_main_menu(update, context)
    
    async def show_shop(self, update: Update, context: CallbackContext):
        """Ürün dükkanını göster"""
        query = update.callback_query
        user_id = update.effective_user.id
        user_points = self.users.get(str(user_id), {}).get('points', 0)
        is_admin = self.is_admin(user_id)
        
        points_display = "SINIRSIZ" if is_admin else user_points
        
        keyboard = []
        for idx, product in enumerate(self.products):
            btn_text = f"{product['emoji']} {product['name']} - {product['points']}⭐"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f'buy_{idx}')])
        
        keyboard.append([InlineKeyboardButton(f"{EMOJIS['refresh']} YENİLE", callback_data='shop'),
                        InlineKeyboardButton(f"{EMOJIS['back']} GERİ", callback_data='back_to_menu')])
        
        msg = f"{EMOJIS['shop']} *ÜRÜN DÜKKANI*\n\n{EMOJIS['money']} *Puanınız:* {points_display}\n\n"
        
        for idx, product in enumerate(self.products):
            can_buy = "✅" if (is_admin or user_points >= product['points']) else "❌"
            msg += f"{can_buy} *{idx+1}. {product['name']}*\n"
            msg += f"   {product['emoji']} {product['points']} puan\n"
            msg += f"   {EMOJIS['info']} {product['desc']}\n\n"
        
        try:
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Shop gösterim hatası: {e}")
    
    async def buy_product(self, update: Update, context: CallbackContext, idx: int):
        """Ürün satın alma"""
        query = update.callback_query
        user_id = update.effective_user.id
        
        if idx >= len(self.products):
            await query.answer("❌ Ürün bulunamadı!")
            return
        
        product = self.products[idx]
        user_points = self.users.get(str(user_id), {}).get('points', 0)
        is_admin = self.is_admin(user_id)
        
        if not is_admin and user_points < product['points']:
            await query.answer(f"❌ Yetersiz puan! Gerekli: {product['points']}")
            return
        
        keyboard = [
            [InlineKeyboardButton(f"{EMOJIS['check']} EVET, SATIN AL", callback_data=f'confirm_{idx}'),
             InlineKeyboardButton(f"{EMOJIS['cross']} İPTAL", callback_data='shop')]
        ]
        
        remaining = "SINIRSIZ" if is_admin else user_points - product['points']
        
        msg = (
            f"{EMOJIS['warning']} *SATIN ALMA ONAYI*\n\n"
            f"{product['emoji']} *Ürün:* {product['name']}\n"
            f"{EMOJIS['coin']} *Tutar:* {product['points']} puan\n"
            f"{EMOJIS['money']} *Kalan Puan:* {remaining}\n\n"
            f"Onaylıyor musunuz?"
        )
        
        try:
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Satın alma onayı gösterim hatası: {e}")
    
    async def confirm_purchase(self, update: Update, context: CallbackContext, idx: int):
        """Satın almayı onayla"""
        query = update.callback_query
        user_id = update.effective_user.id
        username = update.effective_user.username or "Kullanıcı"
        first_name = update.effective_user.first_name or "Kullanıcı"
        is_admin = self.is_admin(user_id)
        
        product = self.products[idx]
        
        # Admin değilse puanı düş
        if not is_admin:
            self.users[str(user_id)]['points'] -= product['points']
            self.save_json(self.users_file, self.users)
        
        # Sipariş oluştur
        order_id = f"ORD{datetime.now().strftime('%Y%m%d%H%M%S')}_{user_id}"
        order = {
            'id': order_id,
            'user_id': user_id,
            'username': username,
            'first_name': first_name,
            'product': product['name'],
            'product_points': product['points'],
            'points_paid': product['points'],
            'status': 'pending',
            'date': datetime.now().isoformat(),
            'is_admin': is_admin
        }
        
        self.orders[order_id] = order
        self.save_json(self.orders_file, self.orders)
        
        # Admin kendi siparişini verirse
        if is_admin:
            admin_note = f"Admin siparişi - Otomatik onaylandı"
            order['status'] = 'completed'
            order['admin_note'] = admin_note
            order['completed_at'] = datetime.now().isoformat()
            self.save_json(self.orders_file, self.orders)
            
            try:
                await query.edit_message_text(
                    text=(
                        f"{EMOJIS['success']} *ADMİN SİPARİŞİ ONAYLANDI!*\n\n"
                        f"{EMOJIS['package']} *Sipariş ID:* {order_id}\n"
                        f"{product['emoji']} *Ürün:* {product['name']}\n\n"
                        f"{EMOJIS['info']} Admin siparişiniz otomatik onaylandı."
                    ),
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.error(f"Admin sipariş onayı hatası: {e}")
            
            return
        
        # Normal kullanıcı ise admin'e bildir
        keyboard = [
            [InlineKeyboardButton(f"{EMOJIS['check']} ONAYLA", callback_data=f'approve_{order_id}'),
             InlineKeyboardButton(f"{EMOJIS['cross']} REDDET", callback_data=f'reject_{order_id}')]
        ]
        
        try:
            await self.safe_send_message(
                chat_id=self.admin_id,
                text=(
                    f"{EMOJIS['bell']} *YENİ SİPARİŞ!*\n\n"
                    f"{EMOJIS['package']} *Sipariş ID:* {order_id}\n"
                    f"{EMOJIS['user']} *Kullanıcı:* @{username}\n"
                    f"{EMOJIS['user']} *Ad:* {first_name}\n"
                    f"{EMOJIS['user']} *ID:* {user_id}\n"
                    f"{product['emoji']} *Ürün:* {product['name']}\n"
                    f"{EMOJIS['coin']} *Puan:* {product['points']}\n"
                    f"{EMOJIS['calendar']} *Tarih:* {datetime.now().strftime('%d.%m.%Y %H:%M')}"
                ),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Admin'e bildirim gönderilemedi: {e}")
        
        # Kullanıcıya bilgi
        try:
            await query.edit_message_text(
                text=(
                    f"{EMOJIS['success']} *SİPARİŞ OLUŞTURULDU!*\n\n"
                    f"{EMOJIS['package']} *Sipariş ID:* {order_id}\n"
                    f"{product['emoji']} *Ürün:* {product['name']}\n"
                    f"{EMOJIS['coin']} *Ödenen:* {product['points']} puan\n"
                    f"{EMOJIS['money']} *Kalan Puan:* {self.users[str(user_id)]['points']}\n\n"
                    f"{EMOJIS['info']} Siparişiniz admin onayına gönderildi. Onaylandıktan sonra ürün bilgileri size iletilecek."
                ),
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Sipariş oluşturma bilgisi hatası: {e}")
    
    async def approve_order(self, update: Update, context: CallbackContext, order_id: str):
        """Siparişi onayla"""
        query = update.callback_query
        order = self.orders.get(order_id)
        
        if not order:
            await query.answer("❌ Sipariş bulunamadı!")
            return
        
        # Admin notu için mesaj bekle
        context.user_data['awaiting_order_note'] = order_id
        try:
            await query.edit_message_text(
                text=f"{EMOJIS['success']} Sipariş onaylandı!\n\nŞimdi kullanıcıya gönderilecek ürün bilgilerini yazın:",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Sipariş onay mesajı hatası: {e}")
    
    async def reject_order(self, update: Update, context: CallbackContext, order_id: str):
        """Siparişi reddet"""
        query = update.callback_query
        order = self.orders.get(order_id)
        
        if order:
            # Puanı iade et (admin değilse)
            user_id = order['user_id']
            if str(user_id) in self.users and not order.get('is_admin', False):
                self.users[str(user_id)]['points'] += order['product_points']
                self.save_json(self.users_file, self.users)
            
            # Sipariş durumunu güncelle
            order['status'] = 'rejected'
            order['rejected_at'] = datetime.now().isoformat()
            order['admin_id'] = update.effective_user.id
            self.save_json(self.orders_file, self.orders)
            
            # Kullanıcıya bildir (admin değilse)
            if not order.get('is_admin', False):
                try:
                    await self.safe_send_message(
                        chat_id=user_id,
                        text=f"{EMOJIS['error']} *SİPARİŞ REDDEDİLDİ*\n\nSiparişiniz (ID: {order_id}) reddedildi.\n{order['product_points']} puan hesabınıza iade edildi.",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception as e:
                    logger.error(f"Kullanıcıya red mesajı gönderilemedi: {e}")
        
        try:
            await query.edit_message_text(
                text=f"{EMOJIS['success']} Sipariş reddedildi ve puan iade edildi.",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Sipariş red mesajı hatası: {e}")
    
    async def handle_message(self, update: Update, context: CallbackContext):
        """Mesaj handler'ı"""
        user_id = update.effective_user.id
        
        # Admin notu için mesaj bekleniyorsa
        if 'awaiting_order_note' in context.user_data and self.is_admin(user_id):
            order_id = context.user_data['awaiting_order_note']
            order = self.orders.get(order_id)
            
            if order:
                note = update.message.text
                
                # Siparişi tamamla
                order['status'] = 'completed'
                order['admin_note'] = note
                order['completed_at'] = datetime.now().isoformat()
                order['admin_id'] = user_id
                self.save_json(self.orders_file, self.orders)
                
                # Kullanıcıya gönder
                try:
                    await self.safe_send_message(
                        chat_id=order['user_id'],
                        text=(
                            f"{EMOJIS['package']} *SİPARİŞİNİZ HAZIR!*\n\n"
                            f"{EMOJIS['check']} *Sipariş ID:* {order_id}\n"
                            f"{EMOJIS['shop']} *Ürün:* {order['product']}\n"
                            f"{EMOJIS['info']} *Ürün Bilgileri:*\n{note}\n\n"
                            f"{EMOJIS['success']} Siparişiniz tamamlandı! İyi günlerde kullanın."
                        ),
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception as e:
                    logger.error(f"Kullanıcıya sipariş bilgisi gönderilemedi: {e}")
                    await update.message.reply_text(f"❌ Kullanıcıya mesaj gönderilemedi: {e}")
                
                await update.message.reply_text(
                    f"{EMOJIS['success']} Ürün bilgileri kullanıcıya gönderildi!",
                    parse_mode=ParseMode.MARKDOWN
                )
            
            del context.user_data['awaiting_order_note']
            return
        
        # Broadcast mesajı bekleniyorsa
        if 'broadcast_message' in context.user_data and self.is_admin(user_id):
            message = update.message.text
            
            # Önizleme göster
            await update.message.reply_text(
                f"{EMOJIS['info']} *Duyuru Önizleme:*\n\n{message}\n\n{EMOJIS['users']} {len(self.users)} kullanıcıya gönderilecek.\nOnaylıyor musunuz? (evet/hayır)",
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data['broadcast_content'] = message
            context.user_data['broadcast_confirmation'] = True
            return
        
        # Broadcast onayı bekleniyorsa
        if 'broadcast_confirmation' in context.user_data and self.is_admin(user_id):
            response = update.message.text.lower()
            if response in ['evet', 'yes', 'ok', 'tamam', 'gönder']:
                message = context.user_data['broadcast_content']
                success = 0
                failed = 0
                
                await update.message.reply_text(f"{EMOJIS['clock']} Duyuru gönderiliyor...")
                
                for uid, user_data in self.users.items():
                    try:
                        # Admin kendine göndermez
                        if int(uid) == user_id:
                            continue
                            
                        await self.safe_send_message(
                            chat_id=int(uid),
                            text=f"{EMOJIS['bell']} *DUYURU*\n\n{message}",
                            parse_mode=ParseMode.MARKDOWN
                        )
                        success += 1
                        
                        # Rate limit için bekle
                        if success % 20 == 0:
                            await asyncio.sleep(1)
                            
                    except Exception as e:
                        logger.error(f"Broadcast gönderilemedi {uid}: {e}")
                        failed += 1
                
                await update.message.reply_text(
                    f"{EMOJIS['success']} Duyuru tamamlandı!\n\nBaşarılı: {success}\nBaşarısız: {failed}"
                )
            else:
                await update.message.reply_text("Duyuru iptal edildi.")
            
            # Temizle
            keys = ['broadcast_message', 'broadcast_content', 'broadcast_confirmation']
            for key in keys:
                if key in context.user_data:
                    del context.user_data[key]
            return
        
        # Normal mesajları ana menüye yönlendir
        await self.show_main_menu(update, context)
    
    async def show_ref_info(self, update: Update, context: CallbackContext):
        """Referans bilgilerini göster"""
        query = update.callback_query
        user_id = update.effective_user.id
        user = self.users.get(str(user_id), {})
        
        ref_code = user.get('referral_code', str(user_id)[-6:])
        bot_username = context.bot.username
        ref_link = f"https://t.me/{bot_username}?start={ref_code}"
        referrals = user.get('referrals', [])
        
        msg = (
            f"{EMOJIS['users']} *REFERANS BİLGİLERİM*\n\n"
            f"{EMOJIS['star']} *Referans Kodum:* `{ref_code}`\n"
            f"{EMOJIS['link']} *Davet Linkim:*\n`{ref_link}`\n\n"
            f"{EMOJIS['fire']} *1 DAVET = 1 PUAN*\n\n"
            f"{EMOJIS['trophy']} *Davet Ettiklerim:* {len(referrals)} kişi\n"
        )
        
        if referrals:
            msg += f"\n{EMOJIS['user']} *Son 10 Davet:*\n"
            for ref_id in referrals[-10:]:
                ref_user = self.users.get(str(ref_id), {})
                username = ref_user.get('username', 'kullanıcı')
                msg += f"• @{username}\n"
        
        keyboard = [[InlineKeyboardButton(f"{EMOJIS['back']} GERİ", callback_data='back_to_menu')]]
        
        try:
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Referans bilgisi gösterim hatası: {e}")
    
    async def show_leaderboard(self, update: Update, context: CallbackContext):
        """Liderlik tablosunu göster"""
        query = update.callback_query
        
        # Admin'i hariç tut
        filtered_users = {k: v for k, v in self.users.items() if not v.get('is_admin', False)}
        
        # En çok puanı olan 10 kullanıcı
        top_users = sorted(filtered_users.items(), key=lambda x: x[1].get('points', 0), reverse=True)[:10]
        
        msg = f"{EMOJIS['trophy']} *LİDERLİK TABLOSU*\n\n"
        
        for i, (uid, user) in enumerate(top_users, 1):
            medal = ['🥇', '🥈', '🥉', '4.', '5.', '6.', '7.', '8.', '9.', '10.'][i-1]
            username = user.get('username', f"ID:{uid[-4:]}")
            points = user.get('points', 0)
            referrals = len(user.get('referrals', []))
            
            msg += f"{medal} *{username}*\n"
            msg += f"   {EMOJIS['star']} {points} puan\n"
            msg += f"   {EMOJIS['users']} {referrals} davet\n"
        
        keyboard = [
            [InlineKeyboardButton(f"{EMOJIS['refresh']} YENİLE", callback_data='leaderboard'),
             InlineKeyboardButton(f"{EMOJIS['back']} GERİ", callback_data='back_to_menu')]
        ]
        
        try:
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Liderlik tablosu gösterim hatası: {e}")
    
    async def show_help(self, update: Update, context: CallbackContext):
        """Yardım menüsünü göster"""
        query = update.callback_query
        
        msg = (
            f"{EMOJIS['info']} *YARDIM & BİLGİLENDİRME*\n\n"
            f"{EMOJIS['fire']} *Nasıl Puan Kazanırım?*\n"
            f"1. Referans linkinizi paylaşın\n"
            f"2. Davet ettiğiniz her kişi için 1 puan kazanın\n"
            f"3. Davet edilen kişi kanala katılmalı\n\n"
            f"{EMOJIS['shop']} *Ürünler:*\n"
        )
        
        for product in self.products[:5]:
            msg += f"• {product['name']} - {product['points']} referans\n"
        
        if len(self.products) > 5:
            msg += f"• ... ve daha fazlası\n"
        
        msg += (
            f"\n{EMOJIS['warning']} *Kurallar:*\n"
            f"• Kanal üyeliği zorunludur\n"
            f"• Sahte hesap açmak yasaktır\n"
            f"• Her kullanıcıyı 1 kez davet edebilirsiniz\n\n"
            f"{EMOJIS['link']} *Kanalımız:* @{self.channel_username}\n\n"
            f"{EMOJIS['connection']} *Bağlantı Sorunları İçin:*\n"
            f"• /ping - Bot durumunu kontrol et\n"
            f"• /refresh - Menüyü yenile"
        )
        
        keyboard = [[InlineKeyboardButton(f"{EMOJIS['back']} GERİ", callback_data='back_to_menu')]]
        
        try:
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Yardım menüsü gösterim hatası: {e}")
    
    # ADMIN FONKSİYONLARI
    
    async def admin_panel_command(self, update: Update, context: CallbackContext):
        """Admin panel komutu"""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Bu komutu sadece admin kullanabilir!")
            return
        
        await self.show_admin_panel(update, context)
    
    async def show_admin_panel(self, update: Update, context: CallbackContext):
        """Admin panelini göster"""
        total_users = len(self.users)
        total_orders = len(self.orders)
        pending_orders = sum(1 for o in self.orders.values() if o.get('status') == 'pending')
        total_points = sum(u.get('points', 0) for k, u in self.users.items() if not u.get('is_admin', False))
        
        # Aktif kullanıcılar (son 7 gün)
        week_ago = datetime.now() - timedelta(days=7)
        active_users = sum(1 for u in self.users.values() 
                          if datetime.fromisoformat(u.get('last_active', '2000-01-01')) > week_ago)
        
        keyboard = [
            [InlineKeyboardButton(f"{EMOJIS['chart']} İSTATİSTİKLER", callback_data='admin_stats'),
             InlineKeyboardButton(f"{EMOJIS['users']} KULLANICILAR", callback_data='admin_users')],
            [InlineKeyboardButton(f"{EMOJIS['package']} SİPARİŞLER", callback_data='admin_orders'),
             InlineKeyboardButton(f"{EMOJIS['points']} PUAN EKLE", callback_data='admin_add_points')],
            [InlineKeyboardButton(f"{EMOJIS['bell']} DUYURU", callback_data='admin_broadcast'),
             InlineKeyboardButton(f"{EMOJIS['shop']} ÜRÜN EKLE", callback_data='admin_add_product')],
            [InlineKeyboardButton(f"{EMOJIS['download']} RAPOR AL", callback_data='admin_report'),
             InlineKeyboardButton(f"{EMOJIS['download']} EXPORT", callback_data='admin_export')],
            [InlineKeyboardButton(f"{EMOJIS['cloud']} BACKUP", callback_data='admin_backup'),
             InlineKeyboardButton(f"{EMOJIS['trash']} TEMİZLİK", callback_data='admin_cleanup')],
            [InlineKeyboardButton(f"{EMOJIS['back']} ANA MENÜ", callback_data='back_to_menu'),
             InlineKeyboardButton(f"{EMOJIS['refresh']} YENİLE", callback_data='admin_panel')]
        ]
        
        msg = (
            f"{EMOJIS['crown']} *ADMIN PANELİ*\n\n"
            f"{EMOJIS['users']} *Kullanıcılar:* {total_users}\n"
            f"{EMOJIS['clock']} *Aktif (7 gün):* {active_users}\n"
            f"{EMOJIS['package']} *Siparişler:* {total_orders}\n"
            f"{EMOJIS['warning']} *Bekleyen:* {pending_orders}\n"
            f"{EMOJIS['coin']} *Toplam Puan:* {total_points}\n"
            f"{EMOJIS['shop']} *Ürün Sayısı:* {len(self.products)}\n\n"
            f"{EMOJIS['info']} *Admin Komutları:*\n"
            f"• /addpoints <id> <miktar> - Puan ekle\n"
            f"• /setpoints <id> <miktar> - Puan ayarla\n"
            f"• /broadcast <mesaj> - Duyuru gönder\n"
            f"• /stats - İstatistikler\n"
            f"• /addproduct <isim> <puan> <açıklama>\n"
            f"• /report - Rapor oluştur\n"
            f"• /export - Veri dışa aktar\n"
            f"• /backup - Yedek al\n"
            f"• /ping - Bağlantı testi"
        )
        
        try:
            if update.callback_query:
                await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
                await update.callback_query.answer()
            else:
                await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Admin panel gösterim hatası: {e}")
    
    async def show_admin_stats(self, update: Update, context: CallbackContext):
        """Admin istatistikleri"""
        try:
            total_users = len(self.users)
            total_orders = len(self.orders)
            completed_orders = sum(1 for o in self.orders.values() if o.get('status') == 'completed')
            pending_orders = sum(1 for o in self.orders.values() if o.get('status') == 'pending')
            rejected_orders = sum(1 for o in self.orders.values() if o.get('status') == 'rejected')
            
            total_points = sum(u.get('points', 0) for k, u in self.users.items() if not u.get('is_admin', False))
            total_referrals = sum(len(u.get('referrals', [])) for u in self.users.values())
            
            # Günlük istatistikler
            today = datetime.now().date()
            yesterday = today - timedelta(days=1)
            
            daily_users = sum(1 for u in self.users.values() 
                            if datetime.fromisoformat(u.get('join_date', '2000-01-01')).date() == today)
            daily_orders = sum(1 for o in self.orders.values() 
                             if datetime.fromisoformat(o.get('date', '2000-01-01')).date() == today)
            
            # Aktif kullanıcılar
            week_ago = datetime.now() - timedelta(days=7)
            active_users = sum(1 for u in self.users.values() 
                              if datetime.fromisoformat(u.get('last_active', '2000-01-01')) > week_ago)
            
            msg = (
                f"{EMOJIS['chart']} *DETAYLI İSTATİSTİKLER*\n\n"
                f"{EMOJIS['users']} *Kullanıcılar:*\n"
                f"• Toplam: {total_users}\n"
                f"• Aktif (7 gün): {active_users}\n"
                f"• Bugün Katılan: {daily_users}\n\n"
                f"{EMOJIS['star']} *Puanlar:*\n"
                f"• Toplam: {total_points}\n"
                f"• Ortalama: {total_points/max(active_users, 1):.1f}\n\n"
                f"{EMOJIS['users']} *Referanslar:*\n"
                f"• Toplam: {total_referrals}\n"
                f"• Oran: {total_referrals/max(total_users, 1)*100:.1f}%\n\n"
                f"{EMOJIS['package']} *Siparişler:*\n"
                f"• Toplam: {total_orders}\n"
                f"• Tamamlanan: {completed_orders}\n"
                f"• Bekleyen: {pending_orders}\n"
                f"• Reddedilen: {rejected_orders}\n"
                f"• Bugün: {daily_orders}"
            )
            
            keyboard = [[InlineKeyboardButton(f"{EMOJIS['back']} GERİ", callback_data='admin_panel')]]
            
            if update.callback_query:
                await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
                
        except Exception as e:
            logger.error(f"İstatistik gösterim hatası: {e}")
    
    async def show_admin_users(self, update: Update, context: CallbackContext):
        """Admin kullanıcı listesi"""
        try:
            # Son 10 kullanıcı
            recent_users = list(self.users.items())[-10:]
            
            msg = f"{EMOJIS['users']} *SON 10 KULLANICI*\n\n"
            
            for uid, user in recent_users:
                username = user.get('username', 'Yok')
                points = user.get('points', 0)
                referrals = len(user.get('referrals', []))
                is_admin = user.get('is_admin', False)
                admin_tag = " 👑" if is_admin else ""
                
                join_date = datetime.fromisoformat(user.get('join_date', '2000-01-01')).strftime('%d.%m.%Y')
                
                msg += f"• @{username}{admin_tag}\n"
                msg += f"  ID: `{uid}`\n"
                msg += f"  Puan: {points}\n"
                msg += f"  Davet: {referrals}\n"
                msg += f"  Katılım: {join_date}\n\n"
            
            keyboard = [[InlineKeyboardButton(f"{EMOJIS['back']} GERİ", callback_data='admin_panel')]]
            
            if update.callback_query:
                await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
                
        except Exception as e:
            logger.error(f"Kullanıcı listesi gösterim hatası: {e}")
    
    async def show_admin_orders(self, update: Update, context: CallbackContext):
        """Admin sipariş listesi"""
        try:
            pending_orders = {k: v for k, v in self.orders.items() if v.get('status') == 'pending'}
            
            if not pending_orders:
                msg = f"{EMOJIS['success']} *BEKLEYEN SİPARİŞ YOK!*"
            else:
                msg = f"{EMOJIS['package']} *BEKLEYEN SİPARİŞLER* ({len(pending_orders)})\n\n"
                
                for order_id, order in list(pending_orders.items())[:5]:
                    order_date = datetime.fromisoformat(order.get('date', '2000-01-01')).strftime('%d.%m.%Y %H:%M')
                    msg += f"• *{order['product']}*\n"
                    msg += f"  ID: {order_id}\n"
                    msg += f"  Kullanıcı: @{order['username']}\n"
                    msg += f"  Puan: {order['product_points']}\n"
                    msg += f"  Tarih: {order_date}\n\n"
            
            keyboard = [[InlineKeyboardButton(f"{EMOJIS['back']} GERİ", callback_data='admin_panel')]]
            
            if update.callback_query:
                await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
                
        except Exception as e:
            logger.error(f"Sipariş listesi gösterim hatası: {e}")
    
    async def start_add_points(self, update: Update, context: CallbackContext):
        """Puan ekleme başlat"""
        query = update.callback_query
        await query.answer()
        
        msg = (
            f"{EMOJIS['points']} *PUAN EKLEME*\n\n"
            f"Puan eklemek istediğiniz kullanıcı ID'sini yazın:\n\n"
            f"{EMOJIS['info']} *Son 5 Kullanıcı:*\n"
        )
        
        for uid, user in list(self.users.items())[-5:]:
            if not user.get('is_admin', False):
                msg += f"ID: `{uid}` - @{user.get('username', 'Kullanıcı')}\n"
        
        msg += f"\nİptal etmek için /cancel yazın."
        
        try:
            await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN)
            context.user_data['awaiting_points_user'] = True
        except Exception as e:
            logger.error(f"Puan ekleme başlatma hatası: {e}")
    
    async def start_broadcast_input(self, update: Update, context: CallbackContext):
        """Broadcast başlat"""
        query = update.callback_query
        await query.answer()
        
        msg = (
            f"{EMOJIS['bell']} *DUYURU GÖNDER*\n\n"
            f"Göndermek istediğiniz mesajı yazın:"
        )
        
        try:
            await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN)
            context.user_data['broadcast_message'] = True
        except Exception as e:
            logger.error(f"Broadcast başlatma hatası: {e}")
    
    async def start_add_product(self, update: Update, context: CallbackContext):
        """Ürün ekleme başlat"""
        query = update.callback_query
        await query.answer()
        
        msg = (
            f"{EMOJIS['shop']} *YENİ ÜRÜN EKLE*\n\n"
            f"Kullanım: /addproduct <isim> <puan> <açıklama>\n"
            f"Örnek: /addproduct Spotify Premium 5 Spotify premium hesap"
        )
        
        try:
            await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Ürün ekleme başlatma hatası: {e}")
    
    async def add_points_command(self, update: Update, context: CallbackContext):
        """Komutla puan ekle"""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Bu komutu sadece admin kullanabilir!")
            return
        
        if not context.args or len(context.args) < 2:
            await update.message.reply_text("Kullanım: /addpoints <kullanıcı_id> <miktar>")
            return
        
        user_id = context.args[0]
        try:
            amount = int(context.args[1])
            if amount <= 0:
                await update.message.reply_text("❌ Pozitif bir sayı girin!")
                return
        except ValueError:
            await update.message.reply_text("❌ Geçersiz miktar!")
            return
        
        if user_id in self.users:
            old_points = self.users[user_id]['points']
            self.users[user_id]['points'] += amount
            self.save_json(self.users_file, self.users)
            
            # Kullanıcıya bildir
            try:
                await self.safe_send_message(
                    chat_id=int(user_id),
                    text=(
                        f"{EMOJIS['gift']} *PUAN EKLENDİ!*\n\n"
                        f"Admin size {amount} puan ekledi!\n"
                        f"Eski puan: {old_points}\n"
                        f"Yeni puan: {self.users[user_id]['points']}"
                    ),
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.error(f"Kullanıcıya puan bildirimi gönderilemedi: {e}")
            
            await update.message.reply_text(
                f"{EMOJIS['success']} {amount} puan eklendi!\n"
                f"Kullanıcı: {user_id}\n"
                f"Yeni puan: {self.users[user_id]['points']}"
            )
        else:
            await update.message.reply_text("❌ Kullanıcı bulunamadı!")
    
    async def set_points_command(self, update: Update, context: CallbackContext):
        """Komutla puan ayarla"""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Bu komutu sadece admin kullanabilir!")
            return
        
        if not context.args or len(context.args) < 2:
            await update.message.reply_text("Kullanım: /setpoints <kullanıcı_id> <miktar>")
            return
        
        user_id = context.args[0]
        try:
            amount = int(context.args[1])
            if amount < 0:
                await update.message.reply_text("❌ Negatif olamaz! 0 veya pozitif bir sayı girin.")
                return
        except ValueError:
            await update.message.reply_text("❌ Geçersiz miktar!")
            return
        
        if user_id in self.users:
            old_points = self.users[user_id]['points']
            self.users[user_id]['points'] = amount
            self.save_json(self.users_file, self.users)
            
            # Kullanıcıya bildir
            try:
                await self.safe_send_message(
                    chat_id=int(user_id),
                    text=(
                        f"{EMOJIS['gear']} *PUAN AYARLANDI!*\n\n"
                        f"Admin puanınızı {amount} olarak ayarladı!\n"
                        f"Eski puan: {old_points}\n"
                        f"Yeni puan: {amount}"
                    ),
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.error(f"Kullanıcıya puan bildirimi gönderilemedi: {e}")
            
            await update.message.reply_text(
                f"{EMOJIS['success']} Puan ayarlandı!\n"
                f"Kullanıcı: {user_id}\n"
                f"Yeni puan: {amount}"
            )
        else:
            await update.message.reply_text("❌ Kullanıcı bulunamadı!")
    
    async def add_product_command(self, update: Update, context: CallbackContext):
        """Komutla ürün ekle"""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Bu komutu sadece admin kullanabilir!")
            return
        
        if not context.args or len(context.args) < 3:
            await update.message.reply_text("Kullanım: /addproduct <isim> <puan> <açıklama>")
            return
        
        name = context.args[0]
        try:
            points = int(context.args[1])
            if points <= 0:
                await update.message.reply_text("❌ Pozitif bir sayı girin!")
                return
        except ValueError:
            await update.message.reply_text("❌ Geçersiz puan değeri!")
            return
        
        description = ' '.join(context.args[2:])
        
        # Yeni ürün ID'si
        new_id = max([p['id'] for p in self.products]) + 1 if self.products else 1
        
        # Emoji seç
        emoji = EMOJIS.get(name.lower().split()[0], EMOJIS['package'])
        
        # Ürün ekle
        self.products.append({
            'id': new_id,
            'name': name,
            'points': points,
            'desc': description,
            'emoji': emoji
        })
        
        self.save_json(self.products_file, self.products)
        
        await update.message.reply_text(
            f"{EMOJIS['success']} Ürün eklendi!\n\n"
            f"{emoji} *Ürün:* {name}\n"
            f"{EMOJIS['coin']} *Puan:* {points}\n"
            f"{EMOJIS['info']} *Açıklama:* {description}"
        )
    
    async def broadcast_command(self, update: Update, context: CallbackContext):
        """Komutla broadcast gönder"""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Bu komutu sadece admin kullanabilir!")
            return
        
        if not context.args:
            await update.message.reply_text("Kullanım: /broadcast <mesaj>")
            return
        
        message = ' '.join(context.args)
        success = 0
        failed = 0
        
        await update.message.reply_text(f"{EMOJIS['clock']} Duyuru gönderiliyor...")
        
        for uid, user_data in self.users.items():
            try:
                # Admin kendine göndermez
                if int(uid) == update.effective_user.id:
                    continue
                    
                await self.safe_send_message(
                    chat_id=int(uid),
                    text=f"{EMOJIS['bell']} *DUYURU*\n\n{message}",
                    parse_mode=ParseMode.MARKDOWN
                )
                success += 1
                
                # Rate limit için bekle
                if success % 20 == 0:
                    await asyncio.sleep(1)
                    
            except Exception as e:
                logger.error(f"Broadcast gönderilemedi {uid}: {e}")
                failed += 1
        
        await update.message.reply_text(
            f"{EMOJIS['success']} Duyuru tamamlandı!\n\n"
            f"Başarılı: {success}\n"
            f"Başarısız: {failed}"
        )
    
    async def show_stats_command(self, update: Update, context: CallbackContext):
        """Stats komutu"""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Bu komutu sadece admin kullanabilir!")
            return
        
        await self.show_admin_stats(update, context)
    
    async def generate_report_command(self, update: Update, context: CallbackContext):
        """Rapor oluştur komutu"""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Bu komutu sadece admin kullanabilir!")
            return
        
        await self.generate_report(update, context)
    
    async def generate_report(self, update: Update, context: CallbackContext):
        """Rapor oluştur"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_file = os.path.join(self.reports_dir, f"report_{timestamp}.txt")
            
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write("=" * 60 + "\n")
                f.write(f"REFERANS BOT RAPORU\n")
                f.write(f"Tarih: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n")
                f.write("=" * 60 + "\n\n")
                
                # Genel İstatistikler
                f.write("📊 GENEL İSTATİSTİKLER\n")
                f.write("-" * 40 + "\n")
                f.write(f"Toplam Kullanıcı: {len(self.users)}\n")
                f.write(f"Toplam Sipariş: {len(self.orders)}\n")
                f.write(f"Toplam Ürün: {len(self.products)}\n")
                f.write(f"Admin Sayısı: {sum(1 for u in self.users.values() if u.get('is_admin', False))}\n\n")
                
                # Detaylı Kullanıcı Listesi
                f.write("👤 KULLANICI LİSTESİ\n")
                f.write("-" * 40 + "\n")
                
                for uid, user in self.users.items():
                    if user.get('is_admin', False):
                        continue
                        
                    join_date = datetime.fromisoformat(user.get('join_date', '2000-01-01')).strftime('%d.%m.%Y')
                    last_active = datetime.fromisoformat(user.get('last_active', '2000-01-01')).strftime('%d.%m.%Y %H:%M')
                    
                    f.write(f"\nID: {uid}\n")
                    f.write(f"  Kullanıcı: {user.get('username', 'Yok')}\n")
                    f.write(f"  Ad: {user.get('first_name', 'Yok')}\n")
                    f.write(f"  Puan: {user.get('points', 0)}\n")
                    f.write(f"  Referans Kodu: {user.get('referral_code', 'Yok')}\n")
                    f.write(f"  Davet Sayısı: {len(user.get('referrals', []))}\n")
                    f.write(f"  Toplam Kazanç: {user.get('total_earned', 0)}\n")
                    f.write(f"  Katılım Tarihi: {join_date}\n")
                    f.write(f"  Son Aktif: {last_active}\n")
                    f.write(f"  Kanal Kontrol: {'✓' if user.get('channel_checked', False) else '✗'}\n")
                    
                    # Referansları
                    referrals = user.get('referrals', [])
                    if referrals:
                        f.write(f"  Davet Ettikleri ({len(referrals)}):\n")
                        for ref_id in referrals[:10]:
                            ref_user = self.users.get(str(ref_id), {})
                            f.write(f"    - @{ref_user.get('username', 'Yok')} (ID: {ref_id})\n")
                        if len(referrals) > 10:
                            f.write(f"    ... ve {len(referrals) - 10} kişi daha\n")
                    
                    f.write("-" * 40 + "\n")
            
            # Raporu gönder
            with open(report_file, 'rb') as f:
                if update.callback_query:
                    await update.callback_query.message.reply_document(
                        document=f,
                        caption=f"{EMOJIS['success']} *Rapor Oluşturuldu!*\n\n"
                               f"{EMOJIS['calendar']} Tarih: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
                               f"{EMOJIS['users']} Kullanıcı: {len(self.users)}\n"
                               f"{EMOJIS['package']} Sipariş: {len(self.orders)}",
                        parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    await update.message.reply_document(
                        document=f,
                        caption=f"{EMOJIS['success']} *Rapor Oluşturuldu!*",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    
        except Exception as e:
            logger.error(f"Rapor oluşturma hatası: {e}")
            await update.message.reply_text(f"{EMOJIS['error']} Rapor oluşturulamadı: {e}")
    
    async def export_data_command(self, update: Update, context: CallbackContext):
        """Export komutu"""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Bu komutu sadece admin kullanabilir!")
            return
        
        await self.export_data(update, context)
    
    async def export_data(self, update: Update, context: CallbackContext):
        """Verileri export et"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Kullanıcıları CSV'ye aktar
            users_file = os.path.join(self.reports_dir, f"users_export_{timestamp}.csv")
            with open(users_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['User ID', 'Username', 'First Name', 'Points', 'Referral Code', 
                               'Referrals Count', 'Total Earned', 'Join Date', 'Last Active', 
                               'Channel Checked', 'Is Admin'])
                
                for uid, user in self.users.items():
                    writer.writerow([
                        uid,
                        user.get('username', ''),
                        user.get('first_name', ''),
                        user.get('points', 0),
                        user.get('referral_code', ''),
                        len(user.get('referrals', [])),
                        user.get('total_earned', 0),
                        user.get('join_date', ''),
                        user.get('last_active', ''),
                        user.get('channel_checked', False),
                        user.get('is_admin', False)
                    ])
            
            # CSV'yi gönder
            with open(users_file, 'rb') as f:
                if update.callback_query:
                    await update.callback_query.message.reply_document(
                        document=f,
                        caption=f"{EMOJIS['success']} *Kullanıcı Verileri Export Edildi!*\n\n"
                               f"{EMOJIS['users']} Toplam: {len(self.users)} kullanıcı",
                        parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    await update.message.reply_document(
                        document=f,
                        caption=f"{EMOJIS['success']} *Kullanıcı Verileri Export Edildi!*",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    
        except Exception as e:
            logger.error(f"Export hatası: {e}")
            await update.message.reply_text(f"{EMOJIS['error']} Export edilemedi: {e}")
    
    async def create_backup_command(self, update: Update, context: CallbackContext):
        """Backup komutu"""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Bu komutu sadece admin kullanabilir!")
            return
        
        try:
            success = self.create_backup()
            if success:
                await update.message.reply_text(
                    f"{EMOJIS['success']} Backup başarıyla oluşturuldu!\n\n"
                    f"{EMOJIS['cloud']} Konum: `{self.backup_dir}/`",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(
                    f"{EMOJIS['error']} Backup oluşturulamadı!",
                    parse_mode=ParseMode.MARKDOWN
                )
        except Exception as e:
            logger.error(f"Backup komutu hatası: {e}")
            await update.message.reply_text(f"{EMOJIS['error']} Backup hatası: {e}")
    
    async def ping_command(self, update: Update, context: CallbackContext):
        """Ping komutu - bağlantı testi"""
        user_id = update.effective_user.id
        
        try:
            start_time = datetime.now()
            
            # Bot durum kontrolü
            bot_info = await context.bot.get_me()
            
            # Veritabanı durumu
            users_count = len(self.users)
            orders_count = len(self.orders)
            
            # Bağlantı süresi
            end_time = datetime.now()
            ping_time = (end_time - start_time).total_seconds() * 1000  # ms
            
            msg = (
                f"{EMOJIS['connection']} *BOT DURUM KONTROLÜ*\n\n"
                f"{EMOJIS['check']} *Bot:* @{bot_info.username}\n"
                f"{EMOJIS['check']} *Ping:* {ping_time:.2f} ms\n"
                f"{EMOJIS['check']} *Kullanıcılar:* {users_count}\n"
                f"{EMOJIS['check']} *Siparişler:* {orders_count}\n"
                f"{EMOJIS['check']} *Ürünler:* {len(self.products)}\n"
                f"{EMOJIS['check']} *Bağlantı:* Aktif ✓\n\n"
            )
            
            if self.is_admin(user_id):
                # Admin için ek bilgiler
                msg += (
                    f"{EMOJIS['info']} *Admin Bilgileri:*\n"
                    f"• Admin ID: {self.admin_id}\n"
                    f"• Kanal: @{self.channel_username}\n"
                    f"• Backup: {len(os.listdir(self.backup_dir)) if os.path.exists(self.backup_dir) else 0} dosya\n"
                    f"• Rapor: {len(os.listdir(self.reports_dir)) if os.path.exists(self.reports_dir) else 0} dosya"
                )
            
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
            
        except Exception as e:
            logger.error(f"Ping komutu hatası: {e}")
            await update.message.reply_text(
                f"{EMOJIS['error']} *Bağlantı Hatası!*\n\n"
                f"Hata: {str(e)}\n\n"
                f"{EMOJIS['info']} Proxy/Network ayarlarını kontrol edin.",
                parse_mode=ParseMode.MARKDOWN
            )
    
    async def cleanup_data(self, update: Update, context: CallbackContext):
        """Veri temizliği"""
        query = update.callback_query
        await query.answer()
        
        # Pasif kullanıcıları temizle (30 günden eski)
        month_ago = datetime.now() - timedelta(days=30)
        inactive_users = []
        
        for uid, user in list(self.users.items()):
            if user.get('is_admin', False):
                continue
                
            last_active = datetime.fromisoformat(user.get('last_active', '2000-01-01'))
            if last_active < month_ago and user.get('points', 0) == 0 and len(user.get('referrals', [])) == 0:
                inactive_users.append(uid)
        
        # Temizle
        cleaned = 0
        for uid in inactive_users:
            del self.users[uid]
            cleaned += 1
        
        if cleaned > 0:
            self.save_json(self.users_file, self.users)
            msg = f"{EMOJIS['success']} {cleaned} pasif kullanıcı temizlendi!"
        else:
            msg = f"{EMOJIS['info']} Temizlenecek kullanıcı bulunamadı."
        
        try:
            await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Temizlik mesajı hatası: {e}")
    
    def run(self):
        """Botu başlat"""
        print(f"{EMOJIS['rocket']} Bot başlatılıyor...")
        print(f"{EMOJIS['crown']} Admin ID: {self.admin_id}")
        print(f"{EMOJIS['users']} Kanal: @{self.channel_username}")
        print(f"{EMOJIS['shop']} Ürün Sayısı: {len(self.products)}")
        print(f"{EMOJIS['users']} Kayıtlı Kullanıcı: {len(self.users)}")
        print(f"{EMOJIS['package']} Toplam Sipariş: {len(self.orders)}")
        print(f"{EMOJIS['cloud']} Backup Dizini: {self.backup_dir}/")
        print(f"{EMOJIS['download']} Rapor Dizini: {self.reports_dir}/")
        print(f"{EMOJIS['info']} Timeout Ayarları: 30 saniye")
        print(f"{EMOJIS['connection']} Proxy Ayarları: Aktif")
        
        try:
            self.application.run_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True,
                close_loop=False
            )
        except KeyboardInterrupt:
            print(f"\n{EMOJIS['warning']} Bot durduruluyor...")
            self.create_backup()
            print(f"{EMOJIS['success']} Backup alındı. Güle güle!")
        except Exception as e:
            logger.error(f"Bot çalıştırma hatası: {e}")
            print(f"{EMOJIS['error']} Hata: {e}")
            self.create_backup()

if __name__ == '__main__':
    TOKEN = "8584951790:AAHllxY_xBpp1uLRJ7fvD_kiywBQmsEbpyw"
    
    # Proxy ayarları (opsiyonel - eğer gerekirse)
    # os.environ['HTTP_PROXY'] = 'http://proxy_url:port'
    # os.environ['HTTPS_PROXY'] = 'https://proxy_url:port'
    
    try:
        bot = ReferralBot(TOKEN)
        bot.run()
    except Exception as e:
        print(f"{EMOJIS['error']} Bot başlatılamadı: {e}")
        print(f"{EMOJIS['info']} Lütfen:")
        print("1. Token'ı kontrol edin")
        print("2. İnternet bağlantınızı kontrol edin")
        print("3. Proxy ayarlarınızı kontrol edin")
        print("4. Telegram API'nin erişilebilir olduğundan emin olun")
