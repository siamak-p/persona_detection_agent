
ATTRIBUTE_SCHEMA: dict[str, dict] = {
    "name": {
        "cardinality": "one",
        "aliases": [
            "name", "full name", "full_name",
            "نام", "اسم", "نام کامل", "نام و نام خانوادگی", "اسم من", "نامم", "اسمم",
        ],
        "type": "str",
        "normalize": lambda v: v.strip(),
    },
    "age": {
        "cardinality": "one",
        "aliases": [
            "age", "years old", "years_old",
            "سن", "سال", "سال دارم", "سالمه", "سنم", "چند ساله","چندساله",
        ],
        "type": "int",
        "min": 0,
        "max": 120,
        "normalize": lambda v: max(0, min(120, int(str(v).strip()))),
    },
    "gender": {
        "cardinality": "one",
        "aliases": ["gender", "sex", "جنسیت"],
        "type": "str",
        "normalize": lambda v: v.strip().lower(),
    },
    "date_of_birth": {
        "cardinality": "one",
        "aliases": ["dob", "birth date", "birthday", "تاریخ تولد", "روز تولد"],
        "type": "str",
        "normalize": lambda v: v.strip(), 
    },
    "marital_status": {
        "cardinality": "one",
        "aliases": [
            "marital status", "relationship status",
            "وضعیت تاهل", "وضعیت تأهل", "تأهل", "مجرد", "متاهل", "متأهل",
        ],
        "type": "str",
        "normalize": lambda v: v.strip().lower(),
    },
    "current_location": {
        "cardinality": "one",
        "aliases": [
            "location", "city", "country", "residence",
            "شهر", "کشور", "محل زندگی", "محل سکونت", "شهر سکونت",
        ],
        "type": "str",
        "normalize": lambda v: v.strip(),
    },
    "timezone": {
        "cardinality": "one",
        "aliases": ["timezone", "time zone", "منطقه زمانی"],
        "type": "str",
        "normalize": lambda v: v.strip(),
    },
    "job_title": {
        "cardinality": "one",
        "aliases": [
            "job", "title", "position", "job_title",
            "سمت", "شغل", "عنوان شغلی", "پست", "موقعیت شغلی", "حرفه", "کار", "چه کاری می‌کنم", "چیکار می‌کنم",
        ],
        "type": "str",
        "normalize": lambda v: v.strip(),
    },
    "employer": {
        "cardinality": "one",
        "aliases": [
            "company", "employer", "organization", "workplace",
            "ارگان", "شرکت", "سازمان", "محل کار", "کارفرما", "جایی که کار می‌کنم", "جای کارم",
        ],
        "type": "str",
        "normalize": lambda v: v.strip(),
    },
    "bedtime": {
        "cardinality": "one",
        "aliases": [
            "bedtime", "sleep time", "go to bed",
            "ساعت خواب", "کی می‌خوابم", "چه ساعتی می‌خوابم",
            "تا چه ساعتی بیدارم", "تا کی بیدارم", "شب‌ها تا چند بیدارم",
            "دیر می‌خوابم", "زود می‌خوابم",
        ],
        "type": "str",
        "normalize": lambda v: v.strip(),
    },
    "wake_time": {
        "cardinality": "one",
        "aliases": [
            "wake time", "wake up time", "get up time",
            "ساعت بیدار شدن", "کی بیدار میشم", "چه ساعتی بیدار میشم",
            "صبح‌ها کی پا میشم", "زود بیدار میشم", "دیر بیدار میشم",
        ],
        "type": "str",
        "normalize": lambda v: v.strip(),
    },
    "industry": {
        "cardinality": "one",
        "aliases": ["industry", "صنعت"],
        "type": "str",
        "normalize": lambda v: v.strip().lower(),
    },
    "education_level": {
        "cardinality": "one",
        "aliases": ["education level", "تحصیلات", "مدرک تحصیلی"],
        "type": "str",
        "normalize": lambda v: v.strip(),
    },
    "highest_degree": {
        "cardinality": "one",
        "aliases": ["degree", "highest degree", "مدرک", "مدرک بالاتر"],
        "type": "str",
        "normalize": lambda v: v.strip(),
    },
    "major": {
        "cardinality": "one",
        "aliases": ["major", "field of study", "رشته", "رشته تحصیلی"],
        "type": "str",
        "normalize": lambda v: v.strip(),
    },
    "university": {
        "cardinality": "one",
        "aliases": ["university", "college", "دانشگاه", "کالج"],
        "type": "str",
        "normalize": lambda v: v.strip(),
    },
    "nationality": {
        "cardinality": "one",
        "aliases": ["nationality", "citizenship", "ملیت", "تابعیت"],
        "type": "str",
        "normalize": lambda v: v.strip(),
    },
    "native_language": {
        "cardinality": "one",
        "aliases": ["native language", "mother tongue", "زبان مادری"],
        "type": "str",
        "normalize": lambda v: v.strip(),
    },
    "preferred_language": {
        "cardinality": "one",
        "aliases": ["preferred language", "زبان ترجیحی"],
        "type": "str",
        "normalize": lambda v: v.strip(),
    },
    "years_of_experience": {
        "cardinality": "one",
        "aliases": ["experience years", "years of experience", "سابقه", "سال سابقه"],
        "type": "int",
        "min": 0,
        "max": 80,
        "normalize": lambda v: max(0, min(80, int(str(v).strip()))),
    },
    "personality_type": {
        "cardinality": "one",
        "aliases": [
            "personality", "personality type", "MBTI", "temperament",
            "تیپ شخصیتی", "شخصیت", "نوع شخصیت",
        ],
        "type": "str",
        "normalize": lambda v: v.strip().upper(),
    },
    "life_motto": {
        "cardinality": "one",
        "aliases": [
            "motto", "life motto", "philosophy of life", "belief",
            "شعار زندگی", "اصل زندگی", "فلسفه زندگی", "باور زندگی",
        ],
        "type": "str",
        "normalize": lambda v: v.strip(),
    },


    "work_schedule": {
        "cardinality": "many",
        "item_alias": "work_schedule_item",
        "aliases": [
            "work schedule", "working hours", "work hours", "office hours",
            "ساعت کاری", "ساعات کاری", "ساعت کار", 
            "از ساعت چند تا چند کار می‌کنم", "ساعت شروع کار", "ساعت پایان کار",
            "کارم از ساعت", "ساعت ورود به کار", "ساعت خروج از کار",
        ],
        "normalize": lambda v: v.strip(),
    },
    "work_days": {
        "cardinality": "many",
        "item_alias": "work_day",
        "aliases": [
            "work days", "working days", "workdays",
            "روزهای کاری", "روز کاری", "چه روزهایی کار می‌کنم",
            "کدوم روزها کار می‌کنم", "روزهای هفته که کار می‌کنم",
        ],
        "normalize": lambda v: v.strip(),
    },
    "works_on_holidays": {
        "cardinality": "many",
        "item_alias": "holiday_work",
        "aliases": [
            "works on holidays", "holiday work",
            "تعطیلات هم کار می‌کنم", "روزهای تعطیل هم کار می‌کنم",
            "تعطیلات سر کارم", "جمعه‌ها هم کار می‌کنم", "پنجشنبه‌ها هم کار می‌کنم",
        ],
        "normalize": lambda v: v.strip(),
    },
    "work_shift": {
        "cardinality": "many",
        "item_alias": "shift",
        "aliases": [
            "work shift", "shift type", "shift work",
            "شیفت کاری", "نوع شیفت کاری", "نوبت کاری",
            "شیفت صبح", "شیفت عصر", "شیفت شب", "شیفتی", "گردشی", "شیفت لانگ",
        ],
        "normalize": lambda v: v.strip(),
    },
    
    "skills": {
        "cardinality": "many",
        "item_alias": "skill",
        "aliases": [
            "skill", "skills", "ability", "abilities",
            "مهارت", "مهارت‌ها", "مهارتها", "مهارت های", "توانایی", "توانایی‌ها", "تواناییها", "بلدم", "بلد هستم", "می‌تونم", "میتونم", "یاد گرفتم", "یادگرفتم",
        ],
        "normalize": lambda v: v.strip(),
        "categories": {
            "instrument": {
                "aliases": [
                    "ساز", "نوازندگی", "نوازنده",
                    "instrument", "musician", "play instruments",
                ],
                "item_matchers": [
                    r"\b(پیانو|گیتار|الکتریک گیتار|باس|ویولن|ویولنسل|ویولا|کلارینت|فلوت|ساکسوفون|سنتور|تار|سه[‌\s-]?تار|عود|دف|درام|ترومپت|ترومبون|هارپ|کیبورد|ارگ)\b",
                ],
            },
            "programming": {
                "aliases": ["برنامه‌نویسی", "کدنویسی", "programming", "coding"],
                "item_matchers": [
                    r"\b(python|java(script)?|typescript|go|rust|c\+\+|c#|c|dart|swift|kotlin|php|ruby|scala)\b",
                ],
            },
            "cloud": {
                "aliases": ["aws", "azure", "gcp", "ابر", "cloud"],
                "item_matchers": [r"\b(aws|azure|gcp|cloudfront|s3|ec2|gke|aks)\b"],
            },
            "data": {
                "aliases": ["data", "ml", "ai", "هوش مصنوعی", "داده"],
                "item_matchers": [r"\b(pandas|numpy|pytorch|tensorflow|sklearn|xgboost|llm|rag)\b"],
            },
            "music_vocal": {
                "aliases": ["خوانندگی", "آواز", "vocal", "singing", "singer"],
                "item_matchers": [r"\b(خوانندگی|آواز|vocal|sing(ing|er)?)\b"],
            },
        },
    },
    "hobbies": {
        "cardinality": "many",
        "item_alias": "hobby",
        "aliases": [
            "hobby", "hobbies", "pastime", "activity",
            "تفریح", "سرگرمی", "فعالیت", "سرگرمیها", "تفریحات", "چیزی که برای تفریح انجام می‌دهم", "وقت آزادم",
        ],
        "normalize": lambda v: v.strip(),
    },
    "interests": {
        "cardinality": "many",
        "item_alias": "interest",
        "aliases": [
            "interest", "interests", "passion", "like", "love",
            "علاقه", "علاقه‌مندی", "علاقه‌ها", "علایق", "دوست دارم", "علاقه دارم", "عاشق", "عاشقم", "چیزهایی که دوست دارم", "از ... خوشم می‌آید",
        ],
        "normalize": lambda v: v.strip(),
    },
    "craves": {
        "cardinality": "many",
        "item_alias": "craving",
        "aliases": [
            "craving", "crave", "craves",
            "هوس", "هوس کردن غذا", "غذا هوس کردن", "هوس کردم بخورم",
        ],
        "normalize": lambda v: v.strip(),
    },
    "preferences": {
        "cardinality": "many",
        "item_alias": "preference",
        "aliases": [
            "preference", "preferences", "prefer",
            "ترجیح", "ترجیحات", "سلیقه", "سلیقه ها", "سلیقه های", "سلیقه های من",
        ],
        "normalize": lambda v: v.strip(),
    },
    "languages": {
        "cardinality": "many",
        "item_alias": "language",
        "aliases": [
            "language", "languages", "spoken language", "spoken languages",
            "زبان", "زبانها", "زبان‌ها", "زبانی که بلدم", "زبان مسلط", "صحبت می‌کنم", "حرف میزنم",
        ],
        "normalize": lambda v: v.strip(),
    },
    "certifications": {
        "cardinality": "many",
        "item_alias": "certification",
        "aliases": ["certificate", "certification", "گواهی نامه", "مدرک"],
        "normalize": lambda v: v.strip(),
    },
    "tools": {
        "cardinality": "many",
        "item_alias": "tool",
        "aliases": ["tool", "tools", "ابزار"],
        "normalize": lambda v: v.strip().lower(),
    },
    "frameworks": {
        "cardinality": "many",
        "item_alias": "framework",
        "aliases": ["framework", "frameworks", "فریمورک", "چارچوب"],
        "normalize": lambda v: v.strip(),
    },
    "sports": {
        "cardinality": "many",
        "item_alias": "sport",
        "aliases": ["sport", "sports", "ورزش", "رشته ورزشی"],
        "normalize": lambda v: v.strip(),
    },
    "values": {
        "cardinality": "many",
        "item_alias": "value",
        "aliases": [
            "value", "values", "core value", "principle",
            "ارزش", "ارزشها", "ارزش‌ها", "اصول", "اصل", "مهمه برام", "برام مهمه", "اهمیت داره",
        ],
        "normalize": lambda v: v.strip(),
    },
    "goals": {
        "cardinality": "many",
        "item_alias": "goal",
        "aliases": [
            "goal", "goals", "dream", "aspiration", "ambition",
            "هدف", "اهداف", "هدفم", "آرزو", "آرزوها", "آرزوم", "می‌خوام", "میخوام", "دوست دارم", "قصد دارم",
        ],
        "normalize": lambda v: v.strip(),
    },
    "hates": {
        "cardinality": "many",
        "item_alias": "hate",
        "aliases": [
            "hate", "hates", "disgust", "disgusting", "hatred",
            "تنفر", "نفرت", "متنفر", "متنفرم", "حالم بهم می خوره", "بیزار", "بیزارم", "بدم میاد"
        ],
        "normalize": lambda v: v.strip(),
    },
    "accidents": {
        "cardinality": "many",
        "item_alias": "accident",
        "aliases": [
            "accident", "accidents", "casualty", "casualties",
            "سانحه", "تصادف", "تصادف کردن", "تصادف داشتن", 
        ],
        "normalize": lambda v: v.strip(),
    },
    "deal-breakers": {
        "cardinality": "many",
        "item_alias": "deal-breaker",
        "aliases": [
            "deal-breaker", "deal-breakers", "Line that I do not corss", "line that I should not be crossed", "personal boundry", "personal boundaries",
            "خط قرمز", "خطوط قرمز", "مرزهای اصولی و اخلاقی", "مرزهای اصولی و اخلاقی که نباید قطع شوند",
        ],
        "normalize": lambda v: v.strip(),
    },
    "personality-traits": {
        "cardinality": "many",
        "item_alias": "personality-trait",
        "aliases": [
            "personality-trait", "personality-traits",
            "ویژگی شخصیتی", "ویژگی شخصیتی من", "صفت شخصیتی", "صفات شخصیتی",
        ],
        "normalize": lambda v: v.strip(),
    },
    "tones": {
        "cardinality": "many",
        "item_alias": "tone",
        "aliases": [
            "tone", "tones",
            " لحن بیان من", "طرز بیان من",
        ],
        "normalize": lambda v: v.strip(),
    },
    "tempers": {
        "cardinality": "many",
        "item_alias": "temper",
        "aliases": [
            "temper", "tempers", "mood", "moods"
            "خلق و خو", "خلق و خوی من", "مزاج من", "طبع من",
        ],
        "normalize": lambda v: v.strip(),
    },
}
