"""
Arabic error messages for YouTube issues
"""

YOUTUBE_ERROR_MESSAGES = {
    "bot_detected": """
🚫 **مشكلة مؤقتة مع YouTube**

⚠️ YouTube يحجب الطلبات حالياً بسبب الحماية المتقدمة

🔄 **جاري البحث في منصات أخرى:**
• Spotify 🎵
• SoundCloud 🎶  
• Apple Music 🍎

💡 **نصائح للحصول على أفضل نتائج:**
• استخدم اسم الأغنية بدلاً من الرابط
• جرب رابط Spotify إذا كان متاحاً
• انتظر 10-15 دقيقة ثم حاول مرة أخرى

⏳ نعمل على حل المشكلة نهائياً...
""",
    
    "alternative_found": """
✅ **تم العثور على بديل!**

🎵 سيتم تشغيل الأغنية من منصة أخرى
📱 جودة الصوت ممتازة كما هو متوقع

💡 **نصيحة:** احفظ رابط Spotify للأغاني المفضلة لديك لتجنب هذه المشكلة
""",
    
    "no_alternative": """
😞 **لم نتمكن من العثور على الأغنية**

🔍 **جرب هذه البدائل:**
• ابحث باسم الفنان + اسم الأغنية
• تأكد من صحة الرابط
• جرب رابط من منصة أخرى (Spotify, SoundCloud)

⏰ أو انتظر قليلاً وحاول مرة أخرى
""",
    
    "youtube_working": """
🎉 **عاد YouTube للعمل!**

✅ تم حل المشكلة المؤقتة
🎵 يمكنك الآن استخدام روابط YouTube بشكل طبيعي

شكراً لصبرك! 🙏
"""
}

def get_error_message(error_type: str, **kwargs) -> str:
    """Get localized error message"""
    return YOUTUBE_ERROR_MESSAGES.get(error_type, "حدث خطأ غير متوقع")
