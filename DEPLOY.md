# em-auth — control de suscripciones

Servicio independiente que decide si un correo tiene acceso al panel de
códigos. El panel (`stk.cfynet.xyz`, CODEX-PRO-V2), el bot de Telegram y (a
futuro) la app consultan a este servicio.

## Variables de entorno

| Variable | Obligatoria | Descripción |
|---|---|---|
| `SECRET_KEY` | Sí (producción) | Firma de la sesión del panel admin (`openssl rand -hex 32`). |
| `ADMIN_PASSWORD` | Sí | Contraseña para `/admin`. |
| `SERVICE_API_KEY` | Sí | Secreto compartido panel/bot ↔ em-auth (cabecera `X-Service-Key`). |
| `SUPABASE_URL` | Sí | `https://sbase.cfynet.xyz` (sin barra final). |
| `SUPABASE_ANON_KEY` | Sí | Anon key del proyecto (la misma del APK). |
| `DATABASE_PATH` | No | Por defecto `/data/subscribers.db`. |
| `TZ_NAME` | No | Zona para vencimientos, por defecto `America/Bogota`. |
| `SESSION_TTL_HOURS` | No | Duración de la sesión admin (24 por defecto). |

## Despliegue en Coolify

1. Subir este directorio a un repositorio Git (GitHub).
2. En Coolify: **New Resource → Dockerfile**, puerto `8080`, healthcheck `/health`.
3. **Storage obligatorio**: volumen con mount path `/data` (sin esto se borran
   los suscriptores en cada redeploy).
4. Configurar las variables de entorno de la tabla.
5. Dominio sugerido: `auth.cfynet.xyz` (o el que prefieras). Debe ser HTTPS.
6. Primer acceso: `https://<dominio>/admin` con `ADMIN_PASSWORD`.

## Endpoints

- `POST /authorize` — `X-Service-Key` + `Authorization: Bearer <token Supabase>`.
  Body `{"email": "..."}`. Exige que el token sea válido, que su correo coincida
  con `email` y que la suscripción esté activa. `200` activo / `401`/`403` no.
- `GET /me` — solo `Authorization: Bearer <token>`. Estado del propio correo.
- `POST /authorize-telegram` — `X-Service-Key`. Body `{"chat_id": 123, "email": "..."}`.
  Exige chat vinculado + correo coincidente + suscripción activa.
- `POST /link-telegram` — `X-Service-Key`. Body `{"code": "...", "chat_id": 123}`.
  Vincula un chat con el suscriptor dueño del código (un solo uso).
- `/admin` — alta, renovación manual por fecha, `+30 días`, bloqueo, borrado,
  generación de código de vinculación de Telegram y vínculo manual de `chat_id`.

## Flujo manual de renovación

1. El cliente paga por WhatsApp/Nequi (como hoy).
2. El staff entra a `/admin`, busca el correo y fija la nueva fecha o pulsa
   `+30 días`.
3. El panel y el bot aceptan el correo hasta esa fecha; después queda bloqueado
   automáticamente (comparación de fecha, sin cron).
