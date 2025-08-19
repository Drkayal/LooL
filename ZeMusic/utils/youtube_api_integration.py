"""
YouTube API Integration Wrapper
Provides seamless integration between YouTube API and existing bot functions
"""
import asyncio
from typing import Optional, Dict, Any, Union
from pyrogram.types import Message

try:
    from ZeMusic.platforms.Youtube import youtube_api
    from ZeMusic.utils.arabic_messages import get_error_message
    API_AVAILABLE = True
except ImportError:
    API_AVAILABLE = False

async def enhanced_youtube_info(url: str, message: Optional[Message] = None) -> Optional[Dict[str, Any]]:
    """
    Get YouTube video info using API first, fallback to original method
    
    This function:
    1. Tries YouTube Data API first (fast, reliable)
    2. Falls back to yt-dlp if API fails
    3. Provides user feedback through messages
    """
    
    if not API_AVAILABLE:
        return None
    
    # Extract video ID
    video_id = youtube_api.extract_video_id(url)
    if not video_id:
        return None
    
    # Try API first
    try:
        if message:
            await message.edit_text("🔍 جاري الحصول على معلومات الفيديو...")
        
        api_info = await youtube_api.get_video_info(video_id)
        
        if api_info:
            if message:
                await message.edit_text(f"✅ تم العثور على: {api_info['title']}")
            return api_info
        
    except Exception as e:
        print(f"API fallback error: {e}")
    
    # API failed, user will see original yt-dlp behavior
    if message:
        await message.edit_text("🔄 جاري المحاولة بطريقة أخرى...")
    
    return None

async def smart_youtube_download(url: str, message: Optional[Message] = None, **kwargs) -> Optional[str]:
    """
    Smart YouTube download that uses API info to improve success rate
    
    Process:
    1. Get video info from API (title, duration, etc.)
    2. Use this info to help yt-dlp
    3. Provide better error messages
    4. Suggest alternatives if download fails
    """
    
    # Get info from API first
    video_info = await enhanced_youtube_info(url, message)
    
    if video_info:
        # We have video info, now try to download
        if message:
            title = video_info['title'][:50] + "..." if len(video_info['title']) > 50 else video_info['title']
            await message.edit_text(f"⬇️ جاري تحميل: {title}")
        
        # TODO: Integrate with existing download function
        # This would call the enhanced download with API info
        return None  # Placeholder
    
    else:
        # No API info available, proceed with original method
        if message:
            await message.edit_text("⚠️ معلومات الفيديو غير متاحة، جاري المحاولة...")
        return None

def create_user_friendly_messages():
    """Create user-friendly messages for different scenarios"""
    
    messages = {
        'api_success': "✅ تم العثور على الفيديو بنجاح",
        'api_downloading': "⬇️ جاري التحميل من YouTube...",
        'api_failed_but_trying': "🔄 جاري المحاولة بطريقة بديلة...",
        'suggest_alternatives': """
🚫 **مشكلة في تحميل الفيديو من YouTube**

💡 **جرب هذه البدائل:**
• ابحث باسم الأغنية مباشرة
• استخدم رابط Spotify إذا كان متاحاً
• انتظر قليلاً وحاول مرة أخرى

🎵 **أو اكتب:** `اسم الفنان - اسم الأغنية`
"""
    }
    
    return messages

# Example usage functions
async def example_integration():
    """Example of how to integrate this with existing play commands"""
    
    # In your play command:
    # 1. Check if it's a YouTube URL
    # 2. Try enhanced info first
    # 3. Use the info for better UX
    
    url = "https://www.youtube.com/watch?v=example"
    
    # Get video info using API
    video_info = await enhanced_youtube_info(url)
    
    if video_info:
        print(f"Found: {video_info['title']}")
        print(f"Duration: {video_info['duration']} seconds")
        print(f"Views: {video_info['view_count']:,}")
        
        # Now try to download with this info
        # The existing download function can use this info
    else:
        print("API info not available, using fallback")
