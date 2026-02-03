from fastapi import FastAPI, HTTPException, Query
import httpx
from bs4 import BeautifulSoup
import uvicorn
import re
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="UAF Result Scraper API")

# Add this block right after 'app = FastAPI()'
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, replace "*" with your InfinityFree URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UAF_LOGIN_URL = "https://lms.uaf.edu.pk/login/index.php"
UAF_RESULT_URL = "https://lms.uaf.edu.pk/course/uaf_student_result.php"

@app.post("/fetch")
async def fetch_uaf_results(registration_number: str = Query(..., alias="registration_number")):
    """
    Fetches student results from the UAF portal.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0, verify=False, follow_redirects=True) as client:
            # 1. Fetch login page to get session cookies and token
            response = await client.get(UAF_LOGIN_URL)
            response.raise_for_status()
            
            # Extract token using regex
            token_match = re.search(r"document\.getElementById\('token'\)\.value='(.*?)'", response.text)
            if not token_match:
                raise HTTPException(status_code=500, detail="Could not find security token on UAF page.")
            
            token = token_match.group(1)

            # 2. POST to result page with cookies and token
            payload = {
                "token": token,
                "Register": registration_number
            }
            
            res_response = await client.post(UAF_RESULT_URL, data=payload)
            res_response.raise_for_status()
            
            if "You are not authorize" in res_response.text:
                raise HTTPException(status_code=403, detail="UAF Server denied authorization (Session expired or blocked).")

            # 3. Parse HTML
            soup = BeautifulSoup(res_response.text, 'html.parser')
            
            # Extract Student Name
            # Use regex for flexibility (case/whitespace)
            name_cell = soup.find(string=re.compile("Student Full Name", re.I))
            student_name = "Unknown Student"
            if name_cell:
                name_row = name_cell.find_parent('tr')
                if name_row:
                    cells = name_row.find_all('td')
                    if len(cells) > 1:
                        student_name = cells[1].text.strip()

            # Extract Course Table
            courses = []
            # Find the specific table containing "Course Code"
            tables = soup.find_all('table')
            target_table = None
            for t in tables:
                if t.find(string=re.compile("Course Code", re.I)):
                    target_table = t
                    break
            
            if target_table:
                rows = target_table.find_all('tr')
                # Skip header row(s). Usually the first row is header.
                for row in rows:
                    cols = row.find_all('td')
                    # We need at least 14 columns based on the screenshot/logic
                    if len(cols) >= 12: 
                        courses.append({
                            "Semester": cols[1].text.strip(),
                            "Course Code": cols[3].text.strip(),
                            "Course Title": cols[4].text.strip(),
                            "Credit Hours": cols[5].text.strip(),
                            "Total": cols[10].text.strip(),
                            "Grade": cols[11].text.strip()
                        })

            if not courses:
                debug_info = f"Found {len(tables)} tables. Target table found: {target_table is not None}. "
                if target_table:
                   debug_info += f"Rows: {len(target_table.find_all('tr'))}. "
                # debug_info += f"Preview: {res_response.text[:200]}"
                raise HTTPException(status_code=404, detail=f"No course results found. Debug: {debug_info}")

            return {
                "success": True,
                "student_info": {
                    "registration_number": registration_number,
                    "full_name": student_name,
                    "program": "Inferred Degree", 
                    "department": "" # Leave empty to let PHP infer from courses
                },
                "courses": courses
            }

    except HTTPException as e:
        raise e
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch from UAF: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scraping error: {str(e)}")

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8081))
    uvicorn.run(app, host="0.0.0.0", port=port)


