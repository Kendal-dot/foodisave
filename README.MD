# Foodisave

*Upload a photo of your ingredients → Get AI-generated recipes → Save food from waste*

## What it does

Recipe app that uses AI to identify ingredients from photos and suggest recipes. Built with FastAPI + React.

## Tech Stack

```
Backend:  FastAPI, PostgreSQL, SQLAlchemy, Google Gemini AI
Frontend: React, Vite, Tailwind CSS
Infra:    Docker, AWS S3, Postmark
```

## Quick Start

```bash
# Clone and setup
git clone https://github.com/Kendal-dot/foodisave.git
cd foodisave
cp .env.example .env  # Add your API keys

# Run with Docker
docker-compose up

# Access
Frontend: http://localhost:5173
Backend:  http://localhost:8000/docs
```

## Core Features

- **Photo → Recipe**: Upload ingredient photo, get recipes (uses Gemini Vision API)
- **Smart Search**: Filter by nutrients, ingredients, dietary preferences
- **Recipe Scaling**: Adjust portions, get updated shopping list
- **User System**: Auth with email verification, credit-based AI features

## API Endpoints

```
POST   /v1/ai/suggest_recipe_from_image    # Main AI feature
GET    /v1/search/recipe                   # Search recipes
POST   /v1/user/recipe                     # Save custom recipe
GET    /v1/ai/shopping-list/{recipe_id}    # Generate shopping list
```

## Environment Variables

```bash
# Required
DB_URL=postgresql://...
GEMINI_API_KEY=your_key_here
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
POSTMARK_TOKEN=your_token

# Full list in .env.example
```

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   React     │────▶│   FastAPI    │────▶│ PostgreSQL  │
│   Frontend  │     │   Backend    │     └─────────────┘
└─────────────┘     └──────┬───────┘              
                           │                       
                    ┌──────▼───────┐     ┌─────────────┐
                    │  Gemini AI   │     │   AWS S3    │
                    └──────────────┘     └─────────────┘
```

## Development

```bash
# Backend only
cd backend
pip install -r app/requirements.txt
uvicorn main:app --reload

# Frontend only
cd frontend
npm install
npm run dev

# Database migrations
alembic upgrade head
```

## AI Features Detail

### Image Recognition Pipeline
1. Upload image → NSFW check (TensorFlow)
2. Send to Gemini Vision API
3. Parse ingredient detection response
4. Generate recipe suggestions
5. Store in PostgreSQL

### Credit System
- New users: 100 credits
- Daily bonus: +1 credit (login)
- Image analysis: -2 credits
- Chat/recipe generation: -1 credit
- Auto-refill: +10 credits when hitting 0

## Database Schema

Key tables:
- `users`: Authentication, credits, profile
- `recipes`: 10k+ pre-loaded recipes (Arla/ICA data)
- `user_recipes`: Custom/AI-generated recipes
- `saved_items`: Ingredient inventory tracking

## Production Considerations

- NSFW detection runs on every image upload
- Gemini API has rate limits (handle in production)
- Images stored privately in S3, served through API
- Email verification required for activation

## Contributing

1. Fork the repo
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

## License

MIT