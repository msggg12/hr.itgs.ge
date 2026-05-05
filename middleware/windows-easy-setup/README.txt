HRMS Middleware — მარტივი ლოკალური გაშვება (Windows)
================================================

რატომ არ არის „ვიზუალური პროგრამა HRMS-ში“?
  HRMS ვებში მხოლოდ Middleware API Key-ის გამოშვებაა (Settings).
  ლოკალური ბრიჯი არის ცალკე EXE — აქ არის ერთი JSON + ერთი .cmd.

რა გჭირდება (2 ველი JSON-ში)
----------------------------
1) api_base_url   — შენი HRMS-ის მისამართი, მაგ. https://hr.itgs.ge
2) middleware_key — HRMS → Settings → Worksites & Middleware Keys → Create Key
                    (ერთხელ ჩანს — შეინახე უსაფრთხოდ)

ნაბიჯები
---------
A) ბილდი (ერთხელ, რეპოს root-იდან PowerShell-ში):
     python -m pip install -r requirements.txt pyinstaller
     python scripts\build_middleware.py
   EXE იქნება: dist\middleware\hrms-middleware-bridge.exe

B) დააკოპირე EXE ამ ფოლდერში (windows-easy-setup), სადაც Start-Middleware.cmd ზის,
   ან დატოვე dist-ში და Start-Middleware.cmd თავად ეძებს ..\..\dist\middleware\...

C) ორმაგი დაწკაპუნება Start-Middleware.cmd
   - პირველად გახსნის Notepad-ს hrms-bridge.local.json-ის შესავსებად
   - შემდეგ გაუშვებს: heartbeat (სერვერთან შემოწმება)

D) ZKTeco / Dahua რეჟიმები სხვა ბრძანებებია — იხილე deployment\MIDDLEWARE_BRIDGE.md

შენიშვნა: hrms-bridge.local.json არ უნდა ავიდეს Git-ზე (პერსონალური გასაღები).
