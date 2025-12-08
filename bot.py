import discord
from discord.ext import commands
import aiohttp
import re
import asyncio

# Bot ayarları
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Roblox kullanıcı adı pattern'i (3-20 karakter, harf, rakam ve alt çizgi)
USERNAME_PATTERN = r'\b[A-Za-z0-9_]{3,20}\b'

class RobloxChecker:
    def __init__(self):
        self.session = None
    
    async def create_session(self):
        if not self.session:
            self.session = aiohttp.ClientSession()
    
    async def close_session(self):
        if self.session:
            await self.session.close()
    
    async def get_user_id(self, username):
        """Roblox kullanıcı adından User ID al"""
        try:
            url = "https://users.roblox.com/v1/usernames/users"
            payload = {
                "usernames": [username],
                "excludeBannedUsers": False
            }
            
            async with self.session.post(url, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('data') and len(data['data']) > 0:
                        return data['data'][0]['id']
        except Exception as e:
            print(f"User ID alınırken hata: {e}")
        return None
    
    async def check_join_status(self, user_id):
        """Kullanıcının join ayarlarını kontrol et"""
        try:
            # Kullanıcı profil ayarlarını kontrol et
            url = f"https://accountinformation.roblox.com/v1/users/{user_id}"
            
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    # allowUnauthenticatedJoins true ise joinler açık demektir
                    return data.get('allowUnauthenticatedJoins', False)
                elif response.status == 401:
                    # Bu endpoint authentication gerektiriyor
                    # Alternatif: Games endpoint'ini kullan
                    return await self.check_join_alternative(user_id)
        except Exception as e:
            print(f"Join kontrolü hatası: {e}")
        return False
    
    async def check_join_alternative(self, user_id):
        """Alternatif join kontrolü"""
        try:
            # Kullanıcının presence bilgisini kontrol et
            url = f"https://presence.roblox.com/v1/presence/users"
            payload = {"userIds": [user_id]}
            
            async with self.session.post(url, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('userPresences'):
                        presence = data['userPresences'][0]
                        # Eğer kullanıcının oyun bilgisi alınabiliyorsa, genelde joinler açıktır
                        # Bu kesin değil ama bir göstergedir
                        return presence.get('userPresenceType', 0) > 0
        except Exception as e:
            print(f"Alternatif kontrol hatası: {e}")
        
        # Daha güvenilir yöntem: Kullanıcının profile settings'i
        try:
            url = f"https://www.roblox.com/users/{user_id}/profile"
            async with self.session.get(url) as response:
                if response.status == 200:
                    # Sayfa yükleniyorsa kullanıcı var demektir
                    return True
        except:
            pass
        
        return False

checker = RobloxChecker()

@bot.event
async def on_ready():
    await checker.create_session()
    print(f'{bot.user} olarak giriş yapıldı!')
    print('Bot hazır!')

@bot.command(name='joincheck')
async def check_joins(ctx, channel: discord.TextChannel = None):
    """Belirtilen kanaldaki mesajlarda Roblox kullanıcı adlarını tara"""
    
    if channel is None:
        channel = ctx.channel
    
    await ctx.send(f"🔍 {channel.mention} kanalı taranıyor...")
    
    # Mesajları topla
    usernames = set()
    message_count = 0
    
    try:
        async for message in channel.history(limit=500):
            message_count += 1
            # Mesajdaki potansiyel kullanıcı adlarını bul
            potential_usernames = re.findall(USERNAME_PATTERN, message.content)
            usernames.update(potential_usernames)
        
        await ctx.send(f"📊 {message_count} mesaj tarandı, {len(usernames)} benzersiz potansiyel kullanıcı adı bulundu.")
        
        # Her kullanıcı adını kontrol et
        checked = 0
        open_joins = []
        
        status_msg = await ctx.send("⏳ Kullanıcılar kontrol ediliyor... 0%")
        
        for i, username in enumerate(usernames):
            checked += 1
            
            # Her 5 kullanıcıda bir ilerleme güncelle
            if checked % 5 == 0 or checked == len(usernames):
                progress = int((checked / len(usernames)) * 100)
                await status_msg.edit(content=f"⏳ Kullanıcılar kontrol ediliyor... {progress}% ({checked}/{len(usernames)})")
            
            # User ID al
            user_id = await checker.get_user_id(username)
            
            if user_id:
                # Join durumunu kontrol et
                is_open = await checker.check_join_status(user_id)
                
                if is_open:
                    open_joins.append({
                        'username': username,
                        'user_id': user_id,
                        'profile_url': f"https://www.roblox.com/users/{user_id}/profile"
                    })
            
            # Rate limiting için kısa bekleme
            await asyncio.sleep(0.5)
        
        await status_msg.delete()
        
        # Sonuçları DM ile gönder
        if open_joins:
            dm_content = f"🎮 **Açık Join'li Kullanıcılar** ({len(open_joins)} kullanıcı)\n\n"
            
            for user in open_joins:
                dm_content += f"👤 **{user['username']}**\n"
                dm_content += f"🔗 {user['profile_url']}\n\n"
                
                # Discord mesaj limiti (2000 karakter)
                if len(dm_content) > 1800:
                    try:
                        await ctx.author.send(dm_content)
                        dm_content = ""
                    except discord.Forbidden:
                        await ctx.send("❌ Size DM gönderemiyorum! Lütfen DM'lerinizi açın.")
                        return
            
            # Kalan içeriği gönder
            if dm_content:
                try:
                    await ctx.author.send(dm_content)
                    await ctx.send(f"✅ {len(open_joins)} açık join'li kullanıcı DM'inize gönderildi!")
                except discord.Forbidden:
                    await ctx.send("❌ Size DM gönderemiyorum! Lütfen DM'lerinizi açın.")
        else:
            await ctx.send("❌ Açık join'li kullanıcı bulunamadı.")
            
    except discord.Forbidden:
        await ctx.send("❌ Bu kanalın mesajlarını okuma yetkim yok!")
    except Exception as e:
        await ctx.send(f"❌ Bir hata oluştu: {str(e)}")

@bot.command(name='checkuser')
async def check_single_user(ctx, username: str):
    """Tek bir Roblox kullanıcısını kontrol et"""
    await ctx.send(f"🔍 {username} kontrol ediliyor...")
    
    user_id = await checker.get_user_id(username)
    
    if not user_id:
        await ctx.send(f"❌ {username} kullanıcısı bulunamadı!")
        return
    
    is_open = await checker.check_join_status(user_id)
    
    if is_open:
        await ctx.send(f"✅ **{username}** - Join'ler AÇIK!\n🔗 https://www.roblox.com/users/{user_id}/profile")
        try:
            await ctx.author.send(f"🎮 **{username}** join'leri açık!\n🔗 https://www.roblox.com/users/{user_id}/profile")
        except discord.Forbidden:
            pass
    else:
        await ctx.send(f"❌ **{username}** - Join'ler kapalı veya kontrol edilemiyor.")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Eksik parametre! Kullanım: `!joincheck #kanal` veya `!checkuser kullanıcıadı`")
    elif isinstance(error, commands.ChannelNotFound):
        await ctx.send("❌ Kanal bulunamadı!")
    else:
        await ctx.send(f"❌ Hata: {str(error)}")

# Bot'u başlat
if __name__ == "__main__":
    import os
    TOKEN = os.getenv("DISCORD_TOKEN")
    bot.run(TOKEN)
