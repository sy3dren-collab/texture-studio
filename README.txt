Texture Studio 0.6.2 — Windows 10／11 x64 獨立版

完整解壓縮後，雙擊 TextureStudio.exe。
不需要安裝 Python、執行 setup 或保留原始碼；啟動不顯示終端機。
錯誤紀錄：%LOCALAPPDATA%\TextureStudio\logs\texture-studio.log

保留完整解析度與依預覽數量鋪排存檔，包含隨機數量、疊加修改、印章／明暗筆刷及 BUMP／法線功能。

驗證：151 項測試通過；原生 Windows Script Host 測試在 Wine 略過。
單檔 EXE 已從隔離的中文含空格資料夾，移除外部 Python 路徑後執行，通過 GUI 與實際圖片存檔檢查。
此為 Wine 相容層驗證結果，尚未完成原生 Windows 實機驗證。
詳細結果與 SHA-256 見 windows-validation.json 及 TextureStudio.exe.sha256。

原始碼：https://github.com/sy3dren-collab/texture-studio/tree/v0.6.2
