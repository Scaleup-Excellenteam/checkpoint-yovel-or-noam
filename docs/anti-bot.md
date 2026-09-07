# TSPO Anti-Bot

## מה המערכת עושה

כאשר לקוח פותח חיבור WebSocket, השרת בודק את כתובת ה-IP שלו לפני token,
login או כניסה לחדר. כך כתובת זדונית נחסמת לפני שהיא יכולה להשתמש בצ'אט.

## זרימת ההחלטה

```text
חיבור חדש
-> קריאת כתובת ה-IP
-> בדיקת cache
-> VirusTotal (לכתובת ציבורית)
-> ALLOW או BLOCK עם reason code
```

## החלטות

| מצב | החלטה | reason code |
|---|---|---|
| כתובת פרטית ברשת כיתה/בית | לאפשר | `IP_PRIVATE_NETWORK` |
| VirusTotal מדווח `malicious` | לחסום | `IP_REPUTATION_MALICIOUS` |
| VirusTotal מדווח `suspicious` | לחסום | `IP_REPUTATION_SUSPICIOUS` |
| אין API key או שהשירות אינו זמין | לאפשר ולתעד | `REPUTATION_UNAVAILABLE` |
| כתובת IP לא תקינה | לחסום | `IP_REPUTATION_INVALID` |
| אין דיווחים זדוניים | לאפשר | `IP_REPUTATION_CLEAN` |

## למה בחרנו כך

- חסימה של `malicious` ו-`suspicious` מגינה מפני כתובות עם ראיות למוניטין רע.
- כתובות פרטיות מותרות כדי שלקוחות באותה רשת כיתה יוכלו להתחבר בלי תלות בשירות חיצוני.
- כאשר VirusTotal לא זמין, בחרנו לא להפיל את הצ'אט. ההחלטה נרשמת בלוג כדי שהמצב יהיה גלוי.
- התוצאות נשמרות ב-cache לעשר דקות כדי לא להאט חיבורים ולא לבזבז קריאות API.
- ה-API key נקרא רק מהמשתנה `VIRUSTOTAL_API_KEY`; הוא לא נשמר בקוד או ב-Git.

## פעולה נראית בדמו

לקוח חסום מקבל:

```text
Connection blocked: IP_REPUTATION_MALICIOUS
```

השרת כותב ללוג את ה-IP ואת reason code, בלי מידע רגיש נוסף.
