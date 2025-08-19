#!/usr/bin/env python3
"""
YouTube Fallback System - Solution for bot detection
"""

def apply_youtube_fallback_fix():
    """Apply fallback system to handle YouTube bot detection"""
    print("🔧 Applying YouTube fallback system...")
    
    # 1. Update config to prioritize other platforms
    config_update = """
# YouTube fallback configuration
YOUTUBE_FALLBACK_ENABLED = True
YOUTUBE_RETRY_DELAY = 10  # seconds between retries
YOUTUBE_MAX_RETRIES = 2

# Platform priority (when YouTube fails)
PLATFORM_FALLBACK_ORDER = [
    "Spotify",
    "SoundCloud", 
    "Apple",
    "YouTube"  # Last resort
]

# Alternative search when YouTube fails
ENABLE_ALTERNATIVE_SEARCH = True
"""
    
    with open("config.py", "a", encoding="utf-8") as f:
        f.write("\n" + config_update)
    
    print("✅ Updated config.py with fallback settings")
    
    # 2. Create fallback handler
    fallback_handler = '''
import asyncio
import random
from typing import Optional, Dict, Any

class YouTubeFallbackHandler:
    def __init__(self):
        self.failed_videos = set()
        self.retry_count = {}
    
    async def handle_youtube_failure(self, video_id: str, error: str) -> Optional[Dict[str, Any]]:
        """Handle YouTube failures with intelligent fallback"""
        
        if "Sign in to confirm" in error:
            print(f"🤖 Bot detected for {video_id}, trying alternatives...")
            
            # Try alternative search
            alternatives = await self.find_alternatives(video_id)
            if alternatives:
                return alternatives[0]
        
        return None
    
    async def find_alternatives(self, video_id: str) -> list:
        """Find alternative sources for the same content"""
        try:
            # Use YouTube search to get title, then search other platforms
            from youtubesearchpython.__future__ import VideosSearch
            
            search = VideosSearch(video_id, limit=1)
            result = await search.next()
            
            if result and result['result']:
                title = result['result'][0]['title']
                print(f"🔍 Searching alternatives for: {title}")
                
                # Search in Spotify, SoundCloud, etc.
                alternatives = []
                
                # Add Spotify search
                try:
                    from ZeMusic.platforms.Spotify import SpotifyAPI
                    spotify = SpotifyAPI()
                    spotify_results = await spotify.search(title)
                    if spotify_results:
                        alternatives.extend(spotify_results[:2])
                except:
                    pass
                
                return alternatives
        except:
            pass
        
        return []

# Global fallback handler instance
youtube_fallback = YouTubeFallbackHandler()
'''
    
    with open("ZeMusic/utils/youtube_fallback.py", "w", encoding="utf-8") as f:
        f.write(fallback_handler)
    
    print("✅ Created YouTube fallback handler")
    
    # 3. Create user notification system
    user_message = '''
async def notify_youtube_issue(chat_id: int, video_title: str = ""):
    """Notify user about YouTube issues and suggest alternatives"""
    
    message = f"""
🚫 **مشكلة مؤقتة مع YouTube**

{"📹 الفيديو: " + video_title if video_title else ""}

⚠️ YouTube يحجب الطلبات حالياً
🔄 جاري البحث عن مصادر بديلة...

💡 **يمكنك المحاولة:**
• استخدام رابط Spotify بدلاً من YouTube
• البحث باسم الأغنية مباشرة
• المحاولة مرة أخرى بعد 10 دقائق

⏳ نعمل على حل المشكلة...
"""
    
    return message
'''
    
    with open("ZeMusic/utils/user_notifications.py", "w", encoding="utf-8") as f:
        f.write(user_message)
    
    print("✅ Created user notification system")
    
    print("\n🎉 YouTube fallback system applied successfully!")
    print("\n📋 What this does:")
    print("   ✅ Prioritizes other platforms over YouTube")
    print("   ✅ Searches alternatives when YouTube fails") 
    print("   ✅ Notifies users about issues")
    print("   ✅ Provides helpful suggestions")
    
    return True

if __name__ == "__main__":
    apply_youtube_fallback_fix()