"""
Enhanced YouTube Handler - Combines API info with existing download system
"""
import asyncio
from typing import Optional, Dict, Any, Union
from pyrogram.types import Message

try:
    from .youtube_api_helper import get_youtube_info, is_youtube_url, youtube_api_helper
    API_AVAILABLE = True
except ImportError:
    API_AVAILABLE = False

class EnhancedYouTubeHandler:
    """Enhanced YouTube handler that combines API with existing functionality"""
    
    def __init__(self):
        self.api_available = API_AVAILABLE
        self.fallback_enabled = True
    
    async def get_video_info_fast(self, url: str, message: Optional[Message] = None) -> Optional[Dict[str, Any]]:
        """
        Get video info quickly using API
        This is much faster than yt-dlp for just getting info
        """
        if not self.api_available:
            return None
        
        if not await is_youtube_url(url):
            return None
        
        try:
            if message:
                await message.edit_text("🔍 جاري الحصول على معلومات الفيديو...")
            
            # Get info from API (very fast)
            info = await get_youtube_info(url)
            
            if info:
                if message:
                    title = info['title']
                    if len(title) > 50:
                        title = title[:47] + "..."
                    
                    duration_min = info['duration'] // 60
                    duration_sec = info['duration'] % 60
                    
                    await message.edit_text(
                        f"✅ **{title}**\n"
                        f"⏱️ المدة: {duration_min:02d}:{duration_sec:02d}\n"
                        f"👀 المشاهدات: {info['view_count']:,}\n"
                        f"📺 القناة: {info['channel']}"
                    )
                
                return info
            else:
                if message:
                    await message.edit_text("⚠️ لم يتم العثور على معلومات الفيديو")
                return None
        
        except Exception as e:
            print(f"Enhanced YouTube info error: {e}")
            if message:
                await message.edit_text("🔄 جاري المحاولة بطريقة أخرى...")
            return None
    
    async def download_with_api_info(
        self, 
        url: str, 
        message: Optional[Message] = None,
        original_download_func = None,
        **kwargs
    ) -> Optional[str]:
        """
        Download with API info to improve success rate
        
        Process:
        1. Get info from API first (fast)
        2. Pass this info to help the download process
        3. Provide better user feedback
        """
        
        # Step 1: Get video info from API
        video_info = await self.get_video_info_fast(url, message)
        
        if video_info:
            # We have video info, now try to download
            if message:
                await message.edit_text(f"⬇️ جاري تحميل: {video_info['title'][:40]}...")
            
            # If we have an original download function, call it
            if original_download_func:
                try:
                    result = await original_download_func(url, **kwargs)
                    return result
                except Exception as e:
                    error_str = str(e)
                    if "Sign in to confirm" in error_str:
                        if message:
                            await message.edit_text(
                                f"🚫 **مشكلة في تحميل الفيديو**\n\n"
                                f"📋 العنوان: {video_info['title'][:50]}...\n"
                                f"⚠️ YouTube يحجب التحميل حالياً\n\n"
                                f"💡 **جرب:**\n"
                                f"• البحث بالاسم: `{video_info['title']}`\n"
                                f"• انتظار 10 دقائق والمحاولة مرة أخرى\n"
                                f"• استخدام رابط من منصة أخرى"
                            )
                        return None
                    else:
                        raise e
            else:
                # No download function provided, return info only
                return video_info
        
        else:
            # No API info, proceed with original method
            if message:
                await message.edit_text("🔄 جاري المحاولة بالطريقة التقليدية...")
            
            if original_download_func:
                return await original_download_func(url, **kwargs)
            
            return None
    
    async def suggest_alternatives(self, failed_url: str, message: Optional[Message] = None) -> Optional[str]:
        """Suggest alternatives when YouTube fails"""
        
        if not self.api_available:
            return None
        
        try:
            # Get video info to extract title
            info = await get_youtube_info(failed_url)
            
            if info and message:
                title = info['title']
                
                suggestion_text = f"""
🚫 **فشل تحميل الفيديو من YouTube**

📋 **العنوان:** {title}

💡 **البدائل المقترحة:**

1️⃣ **البحث بالاسم:**
   `{title}`

2️⃣ **البحث المبسط:**
   `{title.split('-')[0].strip() if '-' in title else title.split('|')[0].strip()}`

3️⃣ **محاولة لاحقة:**
   انتظر 15 دقيقة وحاول مرة أخرى

4️⃣ **منصات أخرى:**
   ابحث عن نفس الأغنية في Spotify أو SoundCloud

⏱️ **المدة:** {info['duration']//60}:{info['duration']%60:02d}
📺 **القناة:** {info['channel']}
"""
                await message.edit_text(suggestion_text)
                return title
        
        except Exception as e:
            print(f"Suggestion error: {e}")
        
        return None

# Global instance
enhanced_youtube = EnhancedYouTubeHandler()

# Convenience functions for easy integration
async def get_youtube_info_fast(url: str, message: Optional[Message] = None) -> Optional[Dict[str, Any]]:
    """Quick function to get YouTube info using API"""
    return await enhanced_youtube.get_video_info_fast(url, message)

async def download_youtube_enhanced(
    url: str, 
    message: Optional[Message] = None, 
    original_func = None,
    **kwargs
) -> Optional[str]:
    """Enhanced download function"""
    return await enhanced_youtube.download_with_api_info(url, message, original_func, **kwargs)

async def suggest_youtube_alternatives(url: str, message: Optional[Message] = None) -> Optional[str]:
    """Suggest alternatives when YouTube fails"""
    return await enhanced_youtube.suggest_alternatives(url, message)