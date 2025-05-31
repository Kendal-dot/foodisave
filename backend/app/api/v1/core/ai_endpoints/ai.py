from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, status, Query, File, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import delete, insert, select, update, and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload
from typing import Optional, Annotated
from random import randint
import json
import re
import os
from app.settings import settings
import google.generativeai as genai
import tempfile
import hashlib
import logging
from PIL import Image, UnidentifiedImageError
import PIL
import uuid
import io
from app.db_setup import get_db
from app.s3_utils import upload_image_to_s3

from app.api.v1.core.recipe_endpoints.recipe_db import (
    get_one_recipe_db
)

from app.security import get_current_user

from app.api.v1.core.recipe_endpoints.recipe_db import (
    get_recipe_db,
    get_random_recipe_db
)

from app.api.v1.core.models import (
    Users,
    Recipes,
    UserRecipes,
    Images,
    Comments,
    Messages,
    Reviews,
    SavedItems

)

from app.api.v1.core.schemas import (
    SearchRecipeSchema,
    RandomRecipeSchema,
    ChatRequest,
    SavedItemsSchema,
    UpdateItemSchema
)

from app.db_setup import get_db

router = APIRouter()

GEMINI_API_KEY = settings.GEMINI_API_KEY

# Konfigurera Gemini API
genai.configure(api_key=GEMINI_API_KEY)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


@router.get("/shopping-list/{recipe_id}")
def modify_recipes(recipe_id: int, portions: int, db: Session = Depends(get_db)):
    """ Generate a shopping list for the recipe, scaled to the specified number of servings """

    # Retrieve the recipe object from the database
    recipe = get_one_recipe_db(recipe_id, db)

    # Convert SQLAlchemy object to dictionary
    # You might need to adjust this based on your specific model
    recipe_dict = {
        "name": recipe.name,
        "servings": recipe.servings,
        "ingredients": recipe.ingredients
    }

    # Parse the ingredients string into a more structured format
    ingredients_list = recipe_dict['ingredients'].split(' | ')

    prompt_text = (
        f"Jag har följande recept: {recipe_dict['name']}.\n"
        f"Originalportioner: {recipe_dict['servings']}\n"
        f"Önskat antal portioner: {portions}\n"
        "Ingredienser:\n" +
        "\n".join(ingredients_list) + "\n\n"
        "Uppgift: Skapa en detaljerad inköpslista med justerade ingredienskvantiteter för det önskade antalet portioner.\n"
        "Regler för svaret:\n"
        "1. Svara ENDAST i JSON-format\n"
        "2. Ingen extra text eller förklaringar\n"
        "3. Använd följande JSON-struktur exakt:\n"
        "{\n"
        "  \"recipes\": [\n"
        "    {\n"
        "      \"name\": \"Ingrediensnamn\",\n"
        "      \"amount\": \"Justerad mängd\",\n"
        "      \"unit\": \"Enhet\"\n"
        "    }\n"
        "  ]\n"
        "}"
    )

    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt_text)

        print(" Gemini API Response:", response)

        if response and response.text:
            cleaned_text = response.text.strip()

            # Remove markdown json formatting if present
            cleaned_text = re.sub(r"^```json\n|\n```$", "", cleaned_text)

            # Clean up extra commas and whitespace
            cleaned_text = cleaned_text.strip().rstrip(",")

            try:
                # Parse JSON
                recipes = json.loads(cleaned_text)

                # Validate the JSON structure
                if "recipes" not in recipes:
                    raise ValueError("JSON saknar 'recipes'-nyckeln.")

                return JSONResponse(content={"recipes": recipes["recipes"]})
            except json.JSONDecodeError as e:
                print(" JSON-dekodningsfel:", e)
                raise HTTPException(
                    status_code=500, detail="500: Misslyckades att tolka svaret från AI som JSON")
            except ValueError as e:
                print(" JSON-fel:", e)
                raise HTTPException(
                    status_code=500, detail=f"500: JSON-formatfel - {str(e)}")

        return JSONResponse(content={"recipes": []}, status_code=200)

    except Exception as e:
        print(f" Fel vid API-förfrågan: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Fel vid API-förfrågan: {str(e)}")


@router.get("/suggest-recipe/{recipe_id}")
def modify_recipes(recipe_id: int, db: Session = Depends(get_db)):
    """ Anropar Gemini API för att föreslå recept baserat på ingredienser """

    recipe = get_one_recipe_db(recipe_id, db)

    prompt_text = (
        f"Jag har följande recept: {recipe}. \n"
        "Skapa en detaljerad lista på **tre recept** som liknar detta recept.\n"
        "Ge även näringsinformation per portion: energi (kcal), protein, kolhydrater och fett. \n\n"
        "Svar endast i JSON-format, ingen extra text. \n"
        "Använd exakt följande JSON-struktur:\n"
        "{\n"
        '  "recipes": [\n'
        "    {\n"
        '      "title": "Titel på receptet",\n'
        '      "description": "En kort beskrivning av rätten.",\n'
        '      "category": "Ange kategori: Fågel, Kött, Fisk, Vegetarisk, Frukost, Bakning.",\n'
        '      "ingredients": [\n'
        '        {"name": "Ingrediensnamn", "amount": "Mängd", "unit": "Enhet"}\n'
        "      ],\n"
        '      "instructions": [\n'
        '        "Steg 1: Beskrivning",\n'
        '        "Steg 2: Beskrivning",\n'
        '        "Steg 3: Beskrivning"\n'
        "      ],\n"
        '      "cook_time": "Total tillagningstid (t.ex. 30 min)",\n'
        '      "servings": "Antal portioner (t.ex. 4 portioner)",\n'
        '      "energy": "Antal kcal per portion",\n'
        '      "protein": "Gram protein per portion",\n'
        '      "carbohydrates": "Gram kolhydrater per portion",\n'
        '      "fat": "Gram fett per portion"\n'
        "    }\n"
        "  ]\n"
        "}"
    )

    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt_text)

        #  Logga API-svaret
        print(" Gemini API Response:", response)

        if response and response.text:
            cleaned_text = response.text.strip()

            # ✅ Ta bort markdown ```json ... ``` om det finns
            cleaned_text = re.sub(r"^```json\n|\n```$", "", cleaned_text)

            # ✅ Rensa bort extra kommatecken och blanksteg i slutet av JSON-strängen
            cleaned_text = cleaned_text.strip().rstrip(",")

            try:
                # ✅ Försök att tolka JSON
                recipes = json.loads(cleaned_text)

                # ✅ Kontrollera att JSON innehåller "recipes"-nyckeln
                if "recipes" not in recipes:
                    raise ValueError("JSON saknar 'recipes'-nyckeln.")

                return JSONResponse(content={"recipes": recipes["recipes"]})
            except json.JSONDecodeError as e:
                print(" JSON-dekodningsfel:", e)
                raise HTTPException(
                    status_code=500, detail="500: Misslyckades att tolka svaret från AI som JSON")
            except ValueError as e:
                print(" JSON-fel:", e)
                raise HTTPException(
                    status_code=500, detail=f"500: JSON-formatfel - {str(e)}")

        return JSONResponse(content={"recipes": []}, status_code=200)

    except Exception as e:
        print(f" Fel vid API-förfrågan: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Fel vid API-förfrågan: {str(e)}")


@router.get("/change-ingredients/{recipe_id}")
def modify_recipes(recipe_id: int,
                   ingredients: str = Query(
                       ..., description="Lista över ingredienser, separerade med komma"),
                   db: Session = Depends(get_db)):
    """ Anropar Gemini API för att föreslå recept baserat på ingredienser """

    recipe = get_one_recipe_db(recipe_id, db)

    ingredient_list = [ing.strip() for ing in ingredients.split(",")]

    prompt_text = (
        f"Jag har följande recept: {recipe}. \n"
        f"jag behöver byta ut dessa ingredienser{', '.join(ingredient_list)} med andra ingredienser som passar.\n"
        "Skapa en detaljerad lista på **tre recept** med dem utbytta ingredienserna.\n"
        "Ge även näringsinformation per portion: energi (kcal), protein, kolhydrater och fett. \n\n"
        "Svar endast i JSON-format, ingen extra text. \n"
        "Använd exakt följande JSON-struktur:\n"
        "{\n"
        '  "recipes": [\n'
        "    {\n"
        '      "title": "Titel på receptet",\n'
        '      "description": "En kort beskrivning av rätten.",\n'
        '      "category": "Ange kategori: Fågel, Kött, Fisk, Vegetarisk, Frukost, Bakning.",\n'
        '      "ingredients": [\n'
        '        {"name": "Ingrediensnamn", "amount": "Mängd", "unit": "Enhet"}\n'
        "      ],\n"
        '      "instructions": [\n'
        '        "Steg 1: Beskrivning",\n'
        '        "Steg 2: Beskrivning",\n'
        '        "Steg 3: Beskrivning"\n'
        "      ],\n"
        '      "cook_time": "Total tillagningstid (t.ex. 30 min)",\n'
        '      "servings": "Antal portioner (t.ex. 4 portioner)",\n'
        '      "energy": "Antal kcal per portion",\n'
        '      "protein": "Gram protein per portion",\n'
        '      "carbohydrates": "Gram kolhydrater per portion",\n'
        '      "fat": "Gram fett per portion"\n'
        "    }\n"
        "  ]\n"
        "}"
    )

    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt_text)

        #  Logga API-svaret
        print(" Gemini API Response:", response)

        if response and response.text:
            cleaned_text = response.text.strip()

            # ✅ Ta bort markdown ```json ... ``` om det finns
            cleaned_text = re.sub(r"^```json\n|\n```$", "", cleaned_text)

            # ✅ Rensa bort extra kommatecken och blanksteg i slutet av JSON-strängen
            cleaned_text = cleaned_text.strip().rstrip(",")

            try:
                # ✅ Försök att tolka JSON
                recipes = json.loads(cleaned_text)

                # ✅ Kontrollera att JSON innehåller "recipes"-nyckeln
                if "recipes" not in recipes:
                    raise ValueError("JSON saknar 'recipes'-nyckeln.")

                return JSONResponse(content={"recipes": recipes["recipes"]})
            except json.JSONDecodeError as e:
                print(" JSON-dekodningsfel:", e)
                raise HTTPException(
                    status_code=500, detail="500: Misslyckades att tolka svaret från AI som JSON")
            except ValueError as e:
                print(" JSON-fel:", e)
                raise HTTPException(
                    status_code=500, detail=f"500: JSON-formatfel - {str(e)}")

        return JSONResponse(content={"recipes": []}, status_code=200)

    except Exception as e:
        print(f" Fel vid API-förfrågan: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Fel vid API-förfrågan: {str(e)}")


@router.get("/add-ingredients/{recipe_id}")
def modify_recipes(recipe_id: int,
                   ingredients: str = Query(
                       ..., description="Lista över ingredienser, separerade med komma"),
                   db: Session = Depends(get_db)):
    """ Anropar Gemini API för att föreslå recept baserat på ingredienser """

    recipe = get_one_recipe_db(recipe_id, db)

    ingredient_list = [ing.strip() for ing in ingredients.split(",")]

    prompt_text = (
        f"Jag har följande recept: {recipe}. \n"
        f"jag behöver lägga till dessa ingredienser{', '.join(ingredient_list)}.\n"
        "Skapa en detaljerad lista på **tre recept** med dem tillagda ingredienserna.\n"
        "Ge även näringsinformation per portion: energi (kcal), protein, kolhydrater och fett. \n\n"
        "Svar endast i JSON-format, ingen extra text. \n"
        "Använd exakt följande JSON-struktur:\n"
        "{\n"
        '  "recipes": [\n'
        "    {\n"
        '      "title": "Titel på receptet",\n'
        '      "description": "En kort beskrivning av rätten.",\n'
        '      "category": "Ange kategori: Fågel, Kött, Fisk, Vegetarisk, Frukost, Bakning.",\n'
        '      "ingredients": [\n'
        '        {"name": "Ingrediensnamn", "amount": "Mängd", "unit": "Enhet"}\n'
        "      ],\n"
        '      "instructions": [\n'
        '        "Steg 1: Beskrivning",\n'
        '        "Steg 2: Beskrivning",\n'
        '        "Steg 3: Beskrivning"\n'
        "      ],\n"
        '      "cook_time": "Total tillagningstid (t.ex. 30 min)",\n'
        '      "servings": "Antal portioner (t.ex. 4 portioner)",\n'
        '      "energy": "Antal kcal per portion",\n'
        '      "protein": "Gram protein per portion",\n'
        '      "carbohydrates": "Gram kolhydrater per portion",\n'
        '      "fat": "Gram fett per portion"\n'
        "    }\n"
        "  ]\n"
        "}"
    )

    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt_text)

        #  Logga API-svaret
        print(" Gemini API Response:", response)

        if response and response.text:
            cleaned_text = response.text.strip()

            # ✅ Ta bort markdown ```json ... ``` om det finns
            cleaned_text = re.sub(r"^```json\n|\n```$", "", cleaned_text)

            # ✅ Rensa bort extra kommatecken och blanksteg i slutet av JSON-strängen
            cleaned_text = cleaned_text.strip().rstrip(",")

            try:
                # ✅ Försök att tolka JSON
                recipes = json.loads(cleaned_text)

                # ✅ Kontrollera att JSON innehåller "recipes"-nyckeln
                if "recipes" not in recipes:
                    raise ValueError("JSON saknar 'recipes'-nyckeln.")

                return JSONResponse(content={"recipes": recipes["recipes"]})
            except json.JSONDecodeError as e:
                print(" JSON-dekodningsfel:", e)
                raise HTTPException(
                    status_code=500, detail="500: Misslyckades att tolka svaret från AI som JSON")
            except ValueError as e:
                print(" JSON-fel:", e)
                raise HTTPException(
                    status_code=500, detail=f"500: JSON-formatfel - {str(e)}")

        return JSONResponse(content={"recipes": []}, status_code=200)

    except Exception as e:
        print(f" Fel vid API-förfrågan: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Fel vid API-förfrågan: {str(e)}")


@router.post("/chat", response_model=dict)
async def chat_with_context(request: ChatRequest, current_user: Users = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Tar emot en JSON-body med 'context' (exempelvis en HTML-sida eller text från den aktuella sidan)
    och 'message' (användarens fråga). Dessa kombineras till en prompt som skickas till Gemini‑API:t,
    och svaret returneras som ren text.

    Exempel på request-body:
    {
      "context": "<html>... innehållet på sidan ...</html>",
      "message": "Hur lagar jag detta recept?"
    }
    """
    # Kontrollera att användaren har tillräckligt med credits
    if current_user.credits < 1:
        raise HTTPException(
            status_code=402,
            detail="Du har inte tillräckligt med credits för att utföra denna förfrågan."
        )

    # Dra 5 credits och spara i databasen
    current_user.credits -= 1
    db.commit()

    prompt_text = (
        "Du är en hjälpsam och kreativ kockassistent. "
        "Använd följande kontext från användarens webbsida som bakgrundsinformation:\n"
        f"{request.context}\n\n"
        "Svara endast på användarens fråga om den är relaterad till kontexten fått innan"
        "Användarens fråga: " + request.message + "\n\n"
        "Svara tydligt och koncist på användarens fråga, ENDAST i ren text."
    )

    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt_text)
        if response and response.text:
            return JSONResponse(content={"response": response.text.strip()})
        return JSONResponse(content={"response": "Inget svar mottaget."})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/save-bought-items")
async def save_bought_ingredients(file: UploadFile = File(...),
                                  current_user: Users = Depends(
                                      get_current_user),
                                  db: Session = Depends(get_db)):
    """
    Tar emot en bildfil, sparar den i images-mappen, 
    öppnar bilden med PIL, och anropar Gemini API för att få receptförslag.
    """
    if current_user.credits < 1:
        raise HTTPException(
            status_code=402,
            detail="Du har inte tillräckligt med credits för att utföra denna förfrågan."
        )

    # Dra 5 credits och spara i databasen
    current_user.credits -= 1
    db.commit()

    try:
        # Generera ett unikt filnamn
        file_extension = file.filename.split(
            '.')[-1] if '.' in file.filename else 'jpg'
        unique_filename = f"{uuid.uuid4()}.{file_extension}"

        # Skapa images-mappen om den inte existerar
        images_dir = os.path.join(os.path.dirname(__file__), "images")
        os.makedirs(images_dir, exist_ok=True)

        file_path = os.path.join(images_dir, unique_filename)

        # Spara bilden på disk
        with open(file_path, "wb") as buffer:
            buffer.write(await file.read())

        # Öppna bilden med PIL
        pil_image = Image.open(file_path)

        # Skapa prompt-texten
        prompt_text = (
            "Du är en AI-specialist på att identifiera livsmedelsprodukter. "
            "Analysera bilden och identifiera alla matvaror som finns på bilden. "
            "För varje identifierad vara, extrahera dess namn och storlek (vikt, volym eller antal beroende på kontext). "
            "Om storleken inte är tydlig, gör en kvalificerad gissning baserat på standardstorlekar. "
            "Svar endast i JSON-format, ingen extra text.\n\n"
            "Använd exakt följande JSON-struktur:\n"
            "{\n"
            '  "items": [\n'
            "    {\n"
            '      "name": "Namn på matvaran",\n'
            '      "size": "Storlek eller mängd (t.ex. 500g, 1L, 6-pack)"\n'
            "    }\n"
            "  ]\n"
            "}"
        )

        # Anropa Gemini API med bilden och prompten
        model = genai.GenerativeModel("gemini-2.0-flash")

        print(model.count_tokens([prompt_text, pil_image]))

        response = model.generate_content([prompt_text, pil_image])

        print("Gemini API Response for image analysis:", response)

        if response and response.text:
            cleaned_text = response.text.strip()
            # Ta bort eventuell markdown (```json ... ```)
            cleaned_text = re.sub(r"^```json\n|\n```$", "", cleaned_text)
            cleaned_text = cleaned_text.strip().rstrip(",")

            try:
                result = json.loads(cleaned_text)
                if "items" not in result:
                    raise ValueError("JSON saknar 'items'-nyckeln.")
                return JSONResponse(content={"items": result["items"]})
            except json.JSONDecodeError as e:
                print("JSON-dekodningsfel:", e)
                raise HTTPException(
                    status_code=500, detail="500: Misslyckades att tolka svaret från AI som JSON"
                )

        return JSONResponse(content={"items": []}, status_code=200)
    except Exception as e:
        print(f"Fel vid API-förfrågan: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Fel vid API-förfrågan: {str(e)}")
    finally:
        # Rensa upp hela images-mappen efter användning
        images_dir = os.path.join(os.path.dirname(__file__), "images")
        if os.path.exists(images_dir):
            import shutil
            shutil.rmtree(images_dir)


@router.post("/saved-items")
def save_items(items: SavedItemsSchema,
               current_user: Users = Depends(get_current_user),
               db: Session = Depends(get_db)
               ):

    saved_items = SavedItems(
        item=items.item,
        size=items.size,
        user_id=current_user.id
    )

    db.add(saved_items)
    db.commit()
    return saved_items


@router.get("/saved-items")
def get_saved_items(
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    saved_items = db.scalars(
        select(SavedItems).where(SavedItems.user_id == current_user.id)
    ).all()

    if not saved_items:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="couldnt find any saved items"
        )

    return saved_items


@router.put("/saved-items/{item_id}")
def update_saved_items(
    item_id: int,
    item: UpdateItemSchema,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):

    saved_item = db.scalars(select(SavedItems).where(
        SavedItems.user_id == current_user.id).where(
            SavedItems.id == item_id)).first()

    for key, value in item.model_dump(exclude_unset=True).items():
        if value != "":
            setattr(saved_item, key, value)

    db.commit()
    return saved_item


@router.delete("/saved-items/{item_id}")
def delete_saved_item(
    item_id: int,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):

    item = db.scalars(select(SavedItems).where(
        SavedItems.user_id == current_user.id).where(SavedItems.id == item_id))
    if not item:
        return False

    db.execute(delete(SavedItems).where(SavedItems.user_id ==
               current_user.id).where(SavedItems.id == item_id))

    db.commit()
    return True


@router.post("/suggest_recipe_from_image")
async def suggest_recipe_from_image(
    file: UploadFile = File(...),
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Tar emot en bildfil, sparar den, anropar Gemini API för receptförslag, och drar 2 credits från den inloggade användaren.
    """

    # Kontrollera att användaren har tillräckligt med credits
    if current_user.credits < 2:
        raise HTTPException(
            status_code=402,
            detail="Du har inte tillräckligt med credits för att utföra denna förfrågan."
        )

    # Dra 2 credits och spara i databasen
    current_user.credits -= 2
    db.commit()

    try:
        # Generera ett unikt filnamn
        file_extension = file.filename.split(
            '.')[-1] if '.' in file.filename else 'jpg'
        unique_filename = f"{uuid.uuid4()}.{file_extension}"

        # Skapa images-mappen om den inte existerar
        images_dir = os.path.join(os.path.dirname(__file__), "images")
        os.makedirs(images_dir, exist_ok=True)

        file_path = os.path.join(images_dir, unique_filename)

        # Spara bilden på disk
        with open(file_path, "wb") as buffer:
            buffer.write(await file.read())

        # Öppna bilden med PIL
        pil_image = Image.open(file_path)

        # Skapa prompt-texten
        prompt_text = (
            "Du är en mästerkock och ska nu följa instruktionerna nedan. "
            "Analysera bilden med ingredienser och identifiera de ingredienser som syns i bilden. "
            "Utöver de ingredienser du identifierar, anta att basvaror som salt, peppar, smör och olja redan finns hemma och inkludera dem i receptet om de är nödvändiga. "
            "Skapa en detaljerad lista på ett recept som kan lagas med de ingredienser du har identifierat samt de nödvändiga basvarorna. "
            "Ge även näringsinformation per portion med ENDAST siffran så det är en float: energi (kcal), protein, kolhydrater och fett. \n\n"
            "Svar endast i JSON-format, ingen extra text. \n"
            "Använd exakt följande JSON-struktur:\n"
            "{\n"
            '  "recipes": [\n'
            "    {\n"
            '      "name": "Titel på receptet",\n'
            '      "descriptions": "En kort beskrivning av rätten.",\n'
            '      "category": "Ange kategori: Fågel, Kött, Fisk, Vegetarisk, Frukost, Bakning.",\n'
            '      "ingredients": [\n'
            '        "Ingrediensnamn mängd enhet"\n'
            "      ],\n"
            '      "instructions": [\n'
            '        "Beskrivning",\n'
            '        "Beskrivning",\n'
            '        "Beskrivning"\n'
            "      ],\n"
            '      "cook_time": "Total tillagningstid (t.ex. 30 min)",\n'
            '      "servings": "Antal portioner (t.ex. 4 portioner)",\n'
            '      "calories": "Antal kcal per portion",\n'
            '      "protein": "Gram protein per portion",\n'
            '      "carbohydrates": "Gram kolhydrater per portion",\n'
            '      "fat": "Gram fett per portion"\n'
            "    }\n"
            "  ]\n"
            "}"
        )

        # Anropa Gemini API med bilden och prompten
        model = genai.GenerativeModel("gemini-2.0-flash")

        print(model.count_tokens([prompt_text, pil_image]))

        response = model.generate_content([prompt_text, pil_image])

        print("Gemini API Response for image analysis:", response)

        if response and response.text:
            cleaned_text = response.text.strip()
            # Ta bort eventuell markdown (```json ... ```)
            cleaned_text = re.sub(r"^```json\n|\n```$", "", cleaned_text)
            cleaned_text = cleaned_text.strip().rstrip(",")

            try:
                result = json.loads(cleaned_text)
                if "recipes" not in result:
                    raise ValueError("JSON saknar 'recipes'-nyckeln.")
                return JSONResponse(content={"recipes": result["recipes"]})
            except json.JSONDecodeError as e:
                print("JSON-dekodningsfel:", e)
                raise HTTPException(
                    status_code=500, detail="500: Misslyckades att tolka svaret från AI som JSON")

        return JSONResponse(content={"recipes": []}, status_code=200)
    except Exception as e:
        print(f"Fel vid API-förfrågan: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Fel vid API-förfrågan: {str(e)}")
    finally:
        # Rensa upp hela images-mappen efter användning
        images_dir = os.path.join(os.path.dirname(__file__), "images")
        if os.path.exists(images_dir):
            import shutil
            shutil.rmtree(images_dir)


@router.post("/suggest-recipe-from-plateimage")
async def suggest_recipe_from_plateimage(
    file: UploadFile = File(...),
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Tar emot en bildfil, sparar den i images-mappen, 
    öppnar bilden med PIL, och anropar Gemini API för att få receptförslag.
    """
    # Kontrollera att användaren har tillräckligt med credits
    if current_user.credits < 2:
        raise HTTPException(
            status_code=402,
            detail="Du har inte tillräckligt med credits för att utföra denna förfrågan."
        )

    # Dra 2 credits och spara i databasen
    current_user.credits -= 2
    db.commit()

    try:
        # Generera ett unikt filnamn
        file_extension = file.filename.split(
            '.')[-1] if '.' in file.filename else 'jpg'
        unique_filename = f"{uuid.uuid4()}.{file_extension}"

        # Skapa images-mappen om den inte existerar
        images_dir = os.path.join(os.path.dirname(__file__), "images")
        os.makedirs(images_dir, exist_ok=True)

        file_path = os.path.join(images_dir, unique_filename)

        # Spara bilden på disk
        with open(file_path, "wb") as buffer:
            buffer.write(await file.read())

        # Öppna bilden med PIL
        pil_image = Image.open(file_path)

        # Skapa prompt-texten
        prompt_text = (
            "Du är en mästerkock och ska nu följa instruktionerna nedan. "
            "Analysera och identifiera maträtten på bilden och föreslå ett recept med instruktioerna nedan som passar till den maten du ser på tallriken. "
            "Utöver de ingredienser du identifierar, anta att basvaror som salt, peppar, smör och olja redan finns hemma och inkludera dem i receptet om de är nödvändiga. "
            "Skapa en detaljerad lista på ett recept som kan lagas med de ingredienser du har identifierat samt de nödvändiga basvarorna. "
            "Ge även näringsinformation per portion med ENDAST siffran så det är en float: energi (kcal), protein, kolhydrater och fett. \n\n"
            "Svar endast i JSON-format, ingen extra text. \n"
            "Använd exakt följande JSON-struktur:\n"
            "{\n"
            '  "recipes": [\n'
            "    {\n"
            '      "name": "Titel på receptet",\n'
            '      "descriptions": "En kort beskrivning av rätten.",\n'
            '      "category": "Ange kategori: Fågel, Kött, Fisk, Vegetarisk, Frukost, Bakning.",\n'
            '      "ingredients": [\n'
            '        "Ingrediensnamn mängd enhet"\n'
            "      ],\n"
            '      "instructions": [\n'
            '        "Beskrivning",\n'
            '        "Beskrivning",\n'
            '        "Beskrivning"\n'
            "      ],\n"
            '      "cook_time": "Total tillagningstid (t.ex. 30 min)",\n'
            '      "servings": "Antal portioner (t.ex. 4 portioner)",\n'
            '      "calories": "Antal kcal per portion",\n'
            '      "protein": "Gram protein per portion",\n'
            '      "carbohydrates": "Gram kolhydrater per portion",\n'
            '      "fat": "Gram fett per portion"\n'
            "    }\n"
            "  ]\n"
            "}"
        )

        # Anropa Gemini API med bilden och prompten
        model = genai.GenerativeModel("gemini-2.0-flash")

        print(model.count_tokens([prompt_text, pil_image]))

        response = model.generate_content([prompt_text, pil_image])

        print("Gemini API Response for image analysis:", response)

        if response and response.text:
            cleaned_text = response.text.strip()
            # Ta bort eventuell markdown (```json ... ```)
            cleaned_text = re.sub(r"^```json\n|\n```$", "", cleaned_text)
            cleaned_text = cleaned_text.strip().rstrip(",")

            try:
                result = json.loads(cleaned_text)
                if "recipes" not in result:
                    raise ValueError("JSON saknar 'recipes'-nyckeln.")
                return JSONResponse(content={"recipes": result["recipes"]})
            except json.JSONDecodeError as e:
                print("JSON-dekodningsfel:", e)
                raise HTTPException(
                    status_code=500, detail="500: Misslyckades att tolka svaret från AI som JSON")

        return JSONResponse(content={"recipes": []}, status_code=200)
    except Exception as e:
        print(f"Fel vid API-förfrågan: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Fel vid API-förfrågan: {str(e)}")
    finally:
        # Rensa upp hela images-mappen efter användning
        images_dir = os.path.join(os.path.dirname(__file__), "images")
        if os.path.exists(images_dir):
            import shutil
            shutil.rmtree(images_dir)
