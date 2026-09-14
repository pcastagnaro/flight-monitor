"""End-to-end UI smoke test with disposable DB, no credentials, and fresh Chromium.
Run using a Python environment with requirements-browser.txt and installed Chromium.
Requires npm dependencies in frontend/. Screenshots are written to /tmp by default.
"""

import asyncio
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import httpx
from playwright.async_api import async_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def ready(url):
    async with httpx.AsyncClient() as client:
        for _ in range(120):
            try:
                if (await client.get(url, timeout=1)).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.5)
    raise RuntimeError("Local test server did not become ready")


async def exercise(ui_url, screenshots):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(
            viewport={"width": 1365, "height": 1100}, device_scale_factor=1
        )
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto(ui_url, wait_until="networkidle")
        await page.get_by_text("＋ Crear búsqueda avanzada", exact=True).click()
        await page.get_by_label("Nombre", exact=True).fill(
            "Prueba de búsqueda escalonada"
        )
        await page.get_by_text("Opciones avanzadas · cobertura y fuentes", exact=True).click()
        await page.get_by_label("Máximo de combinaciones", exact=True).fill("4")
        await page.get_by_label("Máximo de llamadas a adaptadores", exact=True).fill(
            "6"
        )
        await page.get_by_role("button", name="Estimar cobertura", exact=True).click()
        await expect(
            page.get_by_text("4 de 32 combinaciones planificadas", exact=False)
        ).to_be_visible()
        await page.get_by_role("button", name="Guardar búsqueda", exact=True).click()
        await expect(page.get_by_label("Búsquedas guardadas")).not_to_have_value("")
        await page.get_by_text("＋ Crear búsqueda avanzada", exact=True).click()
        await page.get_by_role("button", name="Buscar ahora →", exact=True).click()
        await expect(
            page.get_by_role("button", name="Buscar ahora →", exact=True)
        ).to_be_enabled(timeout=15000)
        await page.get_by_role("button", name="Demostración", exact=True).click()
        await expect(
            page.get_by_role("heading", name="4 ofertas · página 1")
        ).to_be_visible()
        await page.get_by_role("button", name="Histórico", exact=True).first.click()
        await expect(
            page.get_by_role("region", name="Histórico de precios")
        ).to_be_visible()
        await expect(
            page.get_by_role("region", name="Histórico de precios").locator("tbody tr")
        ).to_have_count(1)
        await page.get_by_role("button", name="Cerrar", exact=True).click()
        await page.get_by_label("Precio máximo", exact=True).fill("1")
        await expect(
            page.get_by_role("heading", name="0 ofertas · página 1")
        ).to_be_visible()
        await page.get_by_label("Precio máximo", exact=True).fill("")
        await expect(
            page.get_by_role("heading", name="4 ofertas · página 1")
        ).to_be_visible()
        await page.get_by_role("button", name="Buscar ahora →", exact=True).click()
        await expect(
            page.get_by_role("button", name="Buscar ahora →", exact=True)
        ).to_be_enabled(timeout=15000)
        await expect(
            page.get_by_text("0 llamadas a adaptadores", exact=False)
        ).to_be_visible()
        await page.get_by_label("Destino", exact=True).select_option("EZE")
        await expect(
            page.get_by_role("heading", name="2 ofertas · página 1")
        ).to_be_visible()
        await page.get_by_label("Destino", exact=True).select_option("")
        await expect(
            page.get_by_role("heading", name="4 ofertas · página 1")
        ).to_be_visible()
        await page.get_by_text("Más filtros · duración, proveedor y orden", exact=True).click()
        await page.get_by_role("button", name="Precio", exact=True).click()
        await expect(page.locator('th[aria-sort="descending"]')).to_contain_text(
            "Precio"
        )
        await expect(
            page.get_by_role("heading", name="4 ofertas · página 1")
        ).to_be_visible()
        fares = await page.locator(".offers-table .fare").all_text_contents()
        values = [float(f.split()[0].replace(".", "").replace(",", ".")) for f in fares]
        assert values == sorted(values, reverse=True), values
        await page.get_by_label("Proveedor", exact=True).select_option("amadeus")
        await expect(
            page.get_by_role("heading", name="0 ofertas · página 1")
        ).to_be_visible()
        await page.get_by_role("button", name="Limpiar filtros (1)", exact=True).click()
        await expect(
            page.get_by_role("heading", name="4 ofertas · página 1")
        ).to_be_visible()
        await page.get_by_label("Paleta de colores").select_option("ocean")
        await page.get_by_label("Vista compacta").check()
        await page.reload(wait_until="networkidle")
        await expect(page.locator("main")).to_have_attribute("data-palette", "ocean")
        await expect(page.get_by_label("Vista compacta")).to_be_checked()
        await page.get_by_role("button", name="Demostración", exact=True).click()
        await expect(
            page.get_by_role("heading", name="4 ofertas · página 1")
        ).to_be_visible()
        if await page.locator("details.diagnostics").get_attribute("open") is not None:
            await page.locator("details.diagnostics > summary").click()
        await page.screenshot(path=str(screenshots / "desktop.png"), full_page=True)
        await page.set_viewport_size({"width": 390, "height": 844})
        await page.screenshot(path=str(screenshots / "mobile.png"), full_page=True)
        assert await page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        ), "Mobile page overflows horizontally"
        assert not errors, errors
        print(
            "Browser: create, preview, run, demo, history, price/destination filters, cache, desktop/mobile OK"
        )
        await browser.close()


async def main():
    api_port, ui_port = free_port(), free_port()
    api_url = f"http://127.0.0.1:{api_port}"
    ui_url = f"http://127.0.0.1:{ui_port}"
    screenshots = Path(tempfile.mkdtemp(prefix="flight-ui-screenshots-"))
    with tempfile.TemporaryDirectory(prefix="flight-ui-test-") as directory:
        env = os.environ.copy()
        for key in [
            "FLIGHTPOWERS_API_KEY",
            "SERPAPI_API_KEY",
            "TRAVELPAYOUTS_API_TOKEN",
            "DATACRAWLER_API_KEY",
            "AMADEUS_CLIENT_ID",
            "AMADEUS_CLIENT_SECRET",
            "KIWI_API_KEY",
            "RYANAIR_ENABLED",
            "FLIGHTFINDER_ENABLED",
            "FAST_FLIGHTS_ENABLED",
            "GOOGLE_BROWSER_ENABLED",
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_CHAT_ID",
        ]:
            env.pop(key, None)
        env.update(
            DATABASE_URL="sqlite:///" + str(Path(directory) / "ui.db"),
            CORS_ORIGINS=ui_url,
            NEXT_PUBLIC_API_BASE_URL=api_url,
            NEXT_TELEMETRY_DISABLED="1",
            PROVIDER_MAX_CALLS_PER_RUN="10",
            PROVIDER_MONTHLY_CALL_LIMIT="500",
        )
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT / "backend",
            env=env,
            check=True,
        )
        processes = []
        with (Path(directory) / "servers.log").open("w") as log:
            try:
                processes.append(
                    subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "uvicorn",
                            "app.main:app",
                            "--host",
                            "127.0.0.1",
                            "--port",
                            str(api_port),
                        ],
                        cwd=ROOT / "backend",
                        env=env,
                        stdout=log,
                        stderr=log,
                    )
                )
                # Start Next directly so termination also releases the port.
                processes.append(
                    subprocess.Popen(
                        [
                            "node",
                            "node_modules/next/dist/bin/next",
                            "dev",
                            "--hostname",
                            "127.0.0.1",
                            "--port",
                            str(ui_port),
                        ],
                        cwd=ROOT / "frontend",
                        env=env,
                        stdout=log,
                        stderr=log,
                    )
                )
                await asyncio.gather(ready(api_url + "/api/health"), ready(ui_url))
                await exercise(ui_url, screenshots)
                print(f"Screenshots: {screenshots}")
            finally:
                for process in processes:
                    process.terminate()
                    try:
                        process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


if __name__ == "__main__":
    asyncio.run(main())
