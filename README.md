# Calculadora Triple O

Aplicación web para estimar de forma orientativa la huella de carbono de un viaje o evento.

## Requisitos
- Node.js
- Una API key válida de OpenRouteService

## Configuración
1. Instala dependencias:
   ```bash
   npm install
   ```
2. Crea un archivo `.env` en la raíz del proyecto con:
   ```env
   ORS_API_KEY=tu_api_key_aqui
   ```
3. Inicia la aplicación:
   ```bash
   npm start
   ```

## Notas
- El archivo `.env` no debe subirse al repositorio.
- `node_modules` no debe incluirse en GitHub.
- Esta calculadora ofrece una estimación orientativa y depende de supuestos metodológicos simplificados.
