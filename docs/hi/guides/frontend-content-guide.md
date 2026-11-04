# Frontend content guide

किसी भी user-facing screen, landing page, या in-app copy को design या review करते समय इसका उपयोग करें।
Frontend **product का उपयोग करने वाले लोगों** के लिए है, यह document करने के लिए नहीं कि इसे कैसे बनाया गया।

---

## सुनहरा नियम

**Outcomes, actions, और trust signals दिखाएँ। Implementation, org structure, और ops छिपाएँ।**

अगर कोई वाक्य केवल किसी engineer, grant form भरने वाले founder, या repo पढ़ने वाले व्यक्ति को ही समझ आएगा — तो वह default UI में नहीं होना चाहिए।

---

## Frontend पर क्या दिखाएँ

| श्रेणी | उदाहरण |
|----------|----------|
| **Product क्या करता है** | एक पंक्ति का value prop, सरल भाषा में feature के लाभ |
| **User आगे क्या कर सकता है** | Primary CTA, स्पष्ट अगले कदम वाले empty states |
| **User को प्रभावित करने वाला status** | “Message भेज दिया गया”, “Sync हो रहा है…”, “Upload विफल — फिर से कोशिश करें” |
| **User को जो inputs देने होंगे** | Email, password, preferences, उनका अपना content |
| **Trust & safety (user के लिए प्रासंगिक)** | Privacy सारांश, सरल शब्दों में data retention, support contact |
| **Pricing (जब आप बेचते हैं)** | Plans, limits, trial की अवधि — केवल वही जो उनके भुगतान या मिलने वाली चीज़ को बदलता है |
| **Accessibility** | Labels, fields से जुड़ी errors, focus order, contrast — वैकल्पिक नहीं |

### अच्छे patterns

- “एक ही जगह से messages भेजने के लिए अपना LinkedIn account connect करें।”
- “हम आपके credentials इसी device पर locally store करते हैं।”
- “आज के लिए 3 messages scheduled हैं।”

---

## Frontend पर क्या न दिखाएँ

| श्रेणी | यह internal क्यों रहता है |
|----------|------------------------|
| **Tech stack** | React, Next.js, Python, Selenium, Ollama, Postgres — users इन्हें नहीं चुनते |
| **Profit बनाम non-profit status** | Org का tax status अप्रासंगिक है, जब तक product स्वयं fundraising या grants के बारे में *न* हो |
| **Internal tools** | Arka, Cursor, PrivateGPT, SigNoz, CI, Docker, `.env` |
| **Architecture & APIs** | Microservices, webhooks, queue names, model IDs, provider fallbacks |
| **Dev / ops health banners** | “Database connected”, “API healthy”, “Redis up”, “8 posts loaded” — infra checks logs में होने चाहिए, chrome में नहीं |
| **Business classification** | “B2B”, “hackathon project”, “side project”, investors के लिए revenue model |
| **Raw errors & stack traces** | Support flows में Log IDs ठीक हैं; main UI पर stack traces कभी नहीं |
| **Security internals** | Key names, vault paths, OAuth client secrets, token rotation policy |
| **Compliance boilerplate (बिना filter किए)** | पूरे legal entity names, DUNS, internal policy IDs — इसके बजाय link दें |

### खराब patterns (हटाएँ या docs/admin में ले जाएँ)

- “Powered by Selenium + Groq + Arka agent hub.”
- “This is a non-profit research prototype.”
- “Backend: FastAPI on Railway, frontend: Vite.”
- “ROUTE_MODE=symbolic, LLM fallback enabled.”
- “Database connected · API healthy · 8 posts loaded”
- “Postgres OK · Prisma connected · cache warm”

**इसके बजाय उपयोग करें (या पूरी तरह छिपाएँ, जब तक user को कोई action न लेना हो):**

- “8 posts तैयार हैं”
- “ResearchFeed online है — नवीनतम posts browse करें।”
- केवल विफलता पर: “Posts load नहीं हो सके। कुछ देर बाद फिर से कोशिश करें।”

---

## Gray area — केवल जानबूझकर दिखाएँ

| विषय | यह कब दिखाई दे सकता है |
|-------|-------------------|
| **Open source / license** | अगर आप code distribute करते हैं तो Footer या About में; एक छोटी पंक्ति, LICENSE का link |
| **AI / automation** | अगर users को यह जानना ज़रूरी है कि content AI-generated है (disclosure laws, trust) — एक स्पष्ट वाक्य, model names नहीं |
| **Integrations** | “Google से sign in करें” (user action), “Google OAuth client ID configured” नहीं |
| **Non-profit / mission** | अगर mission ही product है तो marketing site का **About** page; app chrome या error toasts में नहीं |
| **Tech details** | Developer docs, `/docs`, README, admin console — default dashboard में कभी नहीं |

---

## Screen-दर-screen checklist

किसी page या modal को ship करने से पहले, पुष्टि करें:

- [ ] हर दिखाई देने वाला label इसका उत्तर देता है कि “*मैं* क्या कर सकता हूँ?” या “*मेरी* चीज़ों का क्या हुआ?”
- [ ] कोई framework, library, या infra names नहीं, जब तक user ने स्पष्ट रूप से developer view न चुना हो
- [ ] कोई profit / non-profit / funding / hackathon भाषा नहीं, जब तक वह page **About** या **Pricing** न हो
- [ ] Errors actionable हों (“अपना password जाँचें”), diagnostic नहीं (“401 from `/api/v1/auth`”)
- [ ] Settings **user choices** (language, notifications) दिखाएँ, **deploy config** (API base URL) नहीं
- [ ] Empty states पहला action सिखाएँ, यह नहीं कि system अंदर से कैसे काम करता है
- [ ] Footer/legal: Privacy & Terms के links, internal runbooks नहीं
- [ ] कोई dev-status strip (database/API/queue health, “N records loaded”) नहीं, जब तक page एक admin console न हो

---

## Copy templates

### Hero / landing

**करें:** “Tabs बदले बिना personalized LinkedIn messages भेजें।”  
**न करें:** “Outbound growth के लिए एक Python automation stack (non-profit MVP)।”

### Settings

**करें:** “LinkedIn account”, “दैनिक send limit”, “Automation रोकें”।  
**न करें:** “LINKEDIN_USERNAME env var”, “ChromeDriver path”, “Arka routing mode”।

### Errors

**करें:** “Sign in नहीं हो सका। अपना email और password जाँचें।”  
**न करें:** “WebDriverException: chrome not reachable (Arka coding-tui baseline).”

### About (वैकल्पिक page)

**करें:** एक paragraph में mission; privacy का link; support से संपर्क।  
**न करें:** पूरा tech appendix, जब तक audience developers न हों और page पर **For developers** label न हो।

### Status / health pages

**करें:** “ResearchFeed online है”, “Feed और sign-in उपलब्ध हैं”, “पढ़ने के लिए 8 posts तैयार हैं”।  
**न करें:** “Database connected · API healthy · 8 posts loaded” — connection checks को log करें; केवल user outcomes दिखाएँ।

---

## Agents और builders के लिए

Arka इस guide को frontend/UI काम, coding-tui plans, और
`frontend_loop` screenshot reviews के लिए **अपने-आप** load करता है (default रूप से `FRONTEND_CONTENT_GUIDE=1`)। Visual tokens और layout के लिए इसे
[Google DESIGN.md guide](./google-design.md) के साथ उपयोग करें।

`~/.config/arka/.env` में वैकल्पिक overrides:

```bash
FRONTEND_CONTENT_GUIDE=1              # default on
FRONTEND_CONTENT_GUIDE_MODE=auto      # auto | always | off
```

ज़रूरत पड़ने पर manually पढ़ें:

```bash
arka md_doc read docs/guides/frontend-content-guide.md
```

MCP के ज़रिए, `arka_markdown` alias `frontend-content-guide` (bundled copy policy) स्वीकार करता है।

UI implement करते समय:

1. User-visible copy में tech stack, profit/non-profit status, या internal tool names paste न करें।
2. Technical notes को code comments, README, या internal docs में रखें — buttons या toasts में नहीं।
3. अगर संदेह हो, तो screen पर कम दिखाएँ; विस्तार के लिए link दें।
4. Duplicate labels पकड़ने के लिए UI बदलावों के बाद `arka ui-copy .` चलाएँ।

---

## त्वरित संदर्भ

| दिखाएँ | छिपाएँ |
|------|------|
| User goals & results | Stack & infrastructure |
| Actionable errors | Stack traces & env keys |
| Users जिन plan limits तक पहुँचते हैं | Profit / non-profit / funding की कहानी |
| सरल privacy सारांश | Internal tool names |
| CTAs & progress | Main app flow में architecture diagrams |
