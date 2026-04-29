# RestoSuite Training & Exam System

## Overview
A web-based certification exam system for RestoSuite product training.
- **146 questions** across 5 modules (KDS, POS, Marketing, Supply Chain, SG/MY Localization)
- **Bilingual** (English + Chinese) with toggle
- **Dynamic URLs** with timestamp+token for secure access
- **Auto-grading** with detailed results and explanations
- **No login required** - access controlled by unique URL
- **SEO blocked** - noindex headers prevent Google indexing

## Quick Start

### Generate Exam URL
```bash
# Basic exam (20 questions, 30 min, 80% pass rate)
python3 /root/restosuite-exam/generate_url.py

# Custom exam
python3 /root/restosuite-exam/generate_url.py \
  --module "POS" \
  --difficulty "L2" \
  --questions 15 \
  --duration 20 \
  --pass-rate 85
```

### Available Modules
- `all` - All modules
- `KDS` - Kitchen Display System (20 questions)
- `POS` - Point of Sale (80 questions)
- `Marketing` - Marketing & Membership (20 questions)
- `Supply Chain` - Supply Chain Management (11 questions)
- `Singapore/Malaysia Localization` - GST, PayNow, SST (15 questions)

### Difficulty Levels
- `L1` - Basic Knowledge (19 questions)
- `L2` - Role-Specific (98 questions)
- `L3` - Advanced Application (29 questions)

## Deployment

### Option 1: Direct Python (Current)
```bash
cd /root/restosuite-exam
python3 -m uvicorn main:app --host 0.0.0.0 --port 8500
```

### Option 2: Docker
```bash
cd /root/restosuite-exam
docker-compose up -d
```

### Nginx Configuration
Add to `/etc/nginx/sites-available/restosuite.sg`:
```nginx
location /training/ {
    proxy_pass http://127.0.0.1:8500;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    add_header X-Robots-Tag "noindex, nofollow" always;
}
```

Then reload nginx:
```bash
sudo nginx -t && sudo systemctl reload nginx
```

## URLs

| Endpoint | Description |
|----------|-------------|
| `/training/exam-XXXX?token=YYYY` | Exam page |
| `/result/XXXX` | Results page |
| `/admin/results` | Admin dashboard |
| `/generate-exam?...` | Generate new exam URL |

## Security Features
- Dynamic URLs with random 8-char ID + 16-char hash token
- 24-hour expiry on all exam links
- `X-Robots-Tag: noindex, nofollow` on all responses
- `robots.txt` blocks all crawlers
- No search engine indexing

## File Structure
```
/root/restosuite-exam/
├── main.py                 # FastAPI application
├── exam.db                 # SQLite database (auto-created)
├── generate_url.py         # URL generator script
├── requirements.txt        # Python dependencies
├── Dockerfile              # Docker config
├── docker-compose.yml      # Docker compose config
├── nginx.conf              # Nginx config snippet
├── templates/
│   ├── index.html          # Landing page
│   ├── exam.html           # Exam interface
│   ├── result.html         # Results page
│   ├── error.html          # Error page
│   └── admin.html          # Admin dashboard
└── README.md               # This file
```

## Question Bank
Source: `/root/.hermes/profiles/benedict/cache/question_bank_final_v2.json`
- 146 questions total
- Bilingual (EN/ZH)
- Difficulty tagged (L1/L2/L3)
- Module tagged

## Admin Dashboard
Access: `https://www.restosuite.sg/training/admin/results`
Shows all exam results with scores, pass/fail status, and completion times.
