# TaskHub

API quản lý công việc theo **Layered Architecture**: API → Service → Repository → Model.
Không cần activate virtualenv — mọi thứ chạy qua `uv`.

## Yêu cầu

- Python 3.12 (đã pin trong `.python-version`)
- [uv](https://docs.astral.sh/uv/)
- Docker Compose

## Cài đặt

```powershell
uv python install 3.12
uv sync --frozen
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
$script = @'
from pathlib import Path
import secrets

path = Path(".env")
lines = path.read_text(encoding="utf-8").splitlines()
def get_value(name):
    prefix = name + "="
    return next((line[len(prefix):] for line in lines if line.startswith(prefix)), "")

def set_value(name, value):
    prefix = name + "="
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = prefix + value
            return
    lines.append(prefix + value)

for name in ("TASKHUB_JWT_SECRET_KEY", "TASKHUB_POSTGRES_PASSWORD"):
    if not get_value(name):
        set_value(name, secrets.token_urlsafe(48))
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
'@
$script | python -
docker compose -f compose.yaml up --build -d --wait
```

Compose starts the API, PostgreSQL, Redis and local Mailpit capture service.
The setup preserves an existing `.env`, signing key, and Postgres password. If
either secret is blank or missing, it writes a random value directly to `.env`
without printing it. Compose passes the Postgres password separately as a
`SecretStr`; SQLAlchemy safely encodes reserved URL characters when building its
connection URL, so passwords containing `@`, `/`, `#`, or `%` work unchanged.
For a manually chosen value, quote it in `.env` if Compose could parse any
characters as comments or whitespace; the same raw value is passed to Postgres
and URL encoding happens inside the application.
The app is at `http://127.0.0.1:8000`; Mailpit's inbox is at
`http://127.0.0.1:8025`. If port 8000 is occupied, set a free host port for this
PowerShell session before `docker compose`, for example:

```powershell
$env:TASKHUB_HTTP_PORT = "8001"
docker compose -f compose.yaml up --build -d --wait
```

Khi đổi port, thay `8000` bằng port đã chọn ở các URL API/health/docs bên dưới.

PostgreSQL and Redis in this stack are private to its Compose network. The
PostgreSQL data uses a dedicated durable `taskhub-stack` volume; it does not
reuse the host-development database volume on port 5433.
`TASKHUB_POSTGRES_PASSWORD` initializes new Postgres volumes only. It does not
change the password stored in an existing volume; do not reset or remove a volume
to rotate it. Keep the `.env` password aligned with the database's current user.

### Chạy ứng dụng trên host

Nếu muốn chạy API bằng `uvicorn` trên host, thay vào đó khởi động riêng
PostgreSQL và Redis local rồi migrate và chạy ứng dụng:

```powershell
docker compose -f compose.local.yaml up -d --wait
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

`.env.example` trỏ database host tới port 5433 và Redis tới 6379. Host workflow
này không có Mailpit; đặt các biến SMTP để dùng SMTP phù hợp hoặc để trống
`TASKHUB_SMTP_HOST` để tắt email.

`uv run alembic downgrade base` removes all tables; use it only for a disposable DB.

### Chuyển database Day 2 cũ

Migration đầu tạo schema theo `day2-brief.md`; revision tiếp theo thêm bảng phiên refresh.
Hai revision cũ
`552a3882346e` và `9e5ac2ec2ba3` không nằm trong migration graph mới. Để chuyển
database có dữ liệu, dừng ứng dụng và tạo backup đã kiểm tra trước. Chạy preflight
(không ghi dữ liệu), sau đó mới chạy lệnh `--apply` rõ ràng:

```powershell
$url = "postgresql+asyncpg://postgres:taskhub@localhost:5432/taskhub_test"
uv run python -m scripts.upgrade_day2_legacy --database-url $url
uv run python -m scripts.upgrade_day2_legacy --database-url $url --apply
uv run alembic current
```

Lệnh mặc định chỉ đọc; tool yêu cầu URL tường minh và từ chối database không có
hậu tố `_test` nếu thiếu `--allow-non-test-database`. Chỉ dùng cờ đó sau khi đã
backup và xác nhận URL đích. Chuyển đổi nằm trong một transaction và giữ dữ liệu:
đổi tên `name`, `created_by_id`, `body`; thêm description, password hash vô hiệu,
màu mặc định và timestamps; label được gắn với project duy nhất trong workspace.
Nếu workspace của label có 0 hoặc nhiều hơn 1 project, preflight dừng trước khi
ghi. Các enum cũ được giữ nguyên; không tự drop type vì chúng có thể còn được
dùng. Lệnh không chạy tự động khi khởi động ứng dụng.

Nếu không thể dùng utility, cách duy nhất được hỗ trợ là backup dữ liệu, xác nhận
đích rõ ràng, tạo database rỗng mới và chạy revision ban đầu; không chạy
`alembic downgrade base` trên database có dữ liệu vì thao tác đó xóa bảng.

## Chạy server

```powershell
uv run uvicorn app.main:app --reload --port 8000
```

- Health: http://127.0.0.1:8000/health
- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc
- OpenAPI: http://127.0.0.1:8000/openapi.json

## API

Canonical: `/api/v1/tasks`. Alias ngắn `/tasks` cũng hoạt động (ẩn khỏi OpenAPI).

Auth: `POST /api/v1/auth/register`, `/login`, `/refresh`, `/logout`;
`GET/PATCH /api/v1/users/me`; `POST /api/v1/users/me/change-password`.
Access tokens dùng Bearer auth; refresh token chỉ nằm trong cookie HttpOnly,
host-only, `Secure`, `SameSite=Lax` mặc định và giới hạn ở `/api/v1/auth`.
Login chấp nhận client không gửi `Origin` như curl, Postman hoặc mobile; nếu header
được gửi, API kiểm tra origin phải trùng origin API hoặc một origin trong
`TASKHUB_FRONTEND_ORIGINS`. Refresh/logout luôn yêu cầu `Origin` hợp lệ vì dùng
refresh cookie. CORS credentials chỉ bật cho danh sách origin tường minh này.
Refresh tokens được xoay vòng và lưu trạng thái thu hồi trong PostgreSQL. Nếu một
refresh token còn hạn đã bị thu hồi được dùng lại, API thu hồi toàn bộ refresh
session của tài khoản. Vì vậy refresh đồng thời ở nhiều tab có thể khiến một
tab dùng lại token cũ và đăng xuất các tab/thiết bị còn lại; ứng dụng browser nên
single-flight refresh và tuần tự hóa các thao tác auth giữa các tab.
Đăng ký luôn cấp role `member`; profile không cho sửa
role, trạng thái hoạt động hoặc mật khẩu. Logout và đổi mật khẩu thu hồi refresh
tokens; access token đã phát hành còn hiệu lực tới khi hết hạn. Mọi task endpoint
cần `Authorization: Bearer <access_token>`. Quyền dựa trên owner hoặc membership
của workspace chứa project; OWNER/EDITOR được ghi, VIEWER chỉ được đọc. Resource
ngoài workspace bị ẩn bằng 404; VIEWER ghi vào resource nhìn thấy nhận 403.

Workspace API: `POST/GET /api/v1/workspaces`, `GET/PATCH/DELETE
/api/v1/workspaces/{id}`, cùng `/members` và `/members/{user_id}`. Owner tạo
workspace, mời user đang hoạt động làm EDITOR/VIEWER, đổi role và xóa member;
OWNER không thể bị đổi role hoặc xóa. Mọi endpoint cần Bearer access token.

Project API: `POST/GET /api/v1/workspaces/{workspace_id}/projects` tạo và liệt
kê project trong workspace; `GET/PATCH/DELETE /api/v1/projects/{project_id}`
đọc, cập nhật, archive/restore bằng `status` (`active`/`archived`) hoặc xóa.
Project mới luôn ở trạng thái `active`; OWNER/EDITOR có thể tạo, sửa và
archive/restore, chỉ OWNER mới có thể xóa vĩnh viễn vì thao tác này cascade xóa
task, label, liên kết và comment. VIEWER chỉ đọc. Workspace của project không
thể đổi. Nested project create/list trả lỗi workspace nếu workspace không tồn
tại hoặc actor không phải thành viên; flat project routes tiếp tục ẩn resource
bằng lỗi project.

Browser client tối giản nằm ở `examples/auth-client.js`. Client chỉ lưu access
token ngắn hạn trong `localStorage` dưới key `taskhub_access_token`; JavaScript
có thể đọc localStorage, nên dùng HTTPS và chỉ giữ access token ngắn hạn. Refresh
token vẫn nằm trong cookie HttpOnly; refresh luôn gửi `credentials: "include"`.
Request được gắn Bearer token, refresh rồi retry đúng một lần sau 401. Refresh
được single-flight và các auth mutation được tuần tự hóa trong từng tab; client
không đồng bộ refresh giữa các tab, nên vẫn có thể xảy ra race giữa nhiều tab.

```js
import { createAuthClient } from "./examples/auth-client.js";
const auth = createAuthClient({ baseUrl: "https://api.example.com/api/v1" });
await auth.login(email, password);
const response = await auth.request(`/tasks?project_id=${projectId}`);
```

Với frontend khác origin, cấu hình origin chính xác, ví dụ
`TASKHUB_FRONTEND_ORIGINS='["https://app.example.com"]'`. Cookie cross-origin
cần cùng site (cùng eTLD+1); `SameSite=None` chỉ dùng cùng Secure và HTTPS.

Trong PowerShell local HTTP, có thể opt out Secure rõ ràng:

```powershell
$env:TASKHUB_REFRESH_COOKIE_SECURE = "false"
```

SDK/curl có thể bỏ `Origin` khi login; refresh/logout cần gửi `Origin` hợp lệ, ví dụ
`Origin: http://127.0.0.1:8000`. Cookie refresh được browser gửi tự động; API
không nhận refresh token trong JSON hoặc Authorization header.

| Method | Path                  | Status | Mô tả                         |
| ------ | --------------------- | ------ | ----------------------------- |
| POST/GET | `/api/v1/workspaces/{workspace_id}/projects` | 201/200 | Tạo hoặc liệt kê project |
| GET/PATCH/DELETE | `/api/v1/projects/{project_id}` | 200/200/204 | Đọc, sửa/archive/restore, xóa project |
| POST   | `/api/v1/tasks`       | 201    | Tạo task trong `project_id`   |
| GET    | `/api/v1/tasks?project_id={uuid}` | 200 | Danh sách project (`q`, `status`, `priority`, `assignee_id`, `page`, `limit`) |
| GET    | `/api/v1/tasks/{id}`  | 200/404| Chi tiết                      |
| PATCH  | `/api/v1/tasks/{id}`  | 200/404| Cập nhật một phần             |
| DELETE | `/api/v1/tasks/{id}`  | 204/404| Xoá                           |
| POST   | `/api/v1/labels`      | 201    | Tạo label trong project       |
| GET    | `/api/v1/labels?project_id={uuid}` | 200 | Danh sách label có phân trang |
| GET/PATCH/DELETE | `/api/v1/labels/{id}` | 200/204/404 | Đọc, sửa, xoá label |
| GET    | `/api/v1/tasks/{id}/labels` | 200 | Danh sách label của task      |
| PUT/DELETE | `/api/v1/tasks/{task_id}/labels/{label_id}` | 204/404 | Gắn hoặc gỡ label |
| POST/GET | `/api/v1/tasks/{id}/comments` | 201/200 | Tạo hoặc liệt kê comment |
| GET/PATCH/DELETE | `/api/v1/comments/{id}` | 200/204/404 | Đọc, sửa, xoá comment của chính tác giả |

Task create/update/read hỗ trợ thêm `priority` (`low`, `medium`, `high`,
`urgent`), `due_date` ISO 8601 có timezone, `assignee_id`; response có thêm
`created_by`. Assignee phải là owner hoặc user đang hoạt động có membership
trong workspace. `due_date` được chuẩn hoá UTC. Task list yêu cầu `project_id`
và hỗ trợ `q` cùng các filter kết hợp AND `status`, `priority`, `assignee_id`.
`q` được trim, tối đa 200 ký tự, không nhận NUL; chuỗi rỗng sau trim bỏ qua tìm
kiếm. Tìm literal, không phân biệt hoa thường trong title hoặc description;
`%`, `_` và `\` không phải wildcard. Unicode tuân theo lower/collation của
PostgreSQL, không có accent folding. Assignee filter chỉ so khớp UUID trên
project hiện tại; UUID không tồn tại hoặc nằm ngoài project trả về danh sách
rỗng mà không kiểm tra user. Không có filter due date hoặc label.

Pagination dùng `page` bắt đầu từ 1 và `limit` mặc định 20 (1–200). Tham số
query `offset` đã bị loại bỏ và trả 422. Alias ẩn `/tasks` dùng cùng `q`, các
filter và pagination.

Khi tạo task có `assignee_id` khác người tạo, hoặc đổi assignee sang user khác
người thao tác, API xếp lịch email sau khi transaction đã commit. Tự giao task
cho chính mình, giữ nguyên assignee, bỏ assignee hoặc task không có assignee thì
không gửi email. Mailpit trong Compose chỉ thu
email local, không relay ra ngoài. Gửi email chạy best-effort trong process của
API; lỗi SMTP không làm hỏng task đã commit, nhưng email chưa xử lý có thể mất
nếu process dừng đột ngột. Đây không phải hàng đợi bền vững và không cam kết
exactly-once.

Label thuộc cố định một project và chỉ gắn được vào task cùng project. Label và
comment dùng response phân trang `{items,total}`. OWNER/EDITOR được ghi;
VIEWER chỉ đọc. Comment chỉ tác giả hiện còn quyền ghi task mới được sửa/xoá.
Các endpoint label/comment chỉ có dưới `/api/v1`; alias ẩn `/tasks` tiếp tục chỉ
phản chiếu CRUD task cũ.

Ví dụ:

```powershell
$password = "<password tối thiểu 12 ký tự>"
$registered = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/auth/register `
  -ContentType "application/json" `
  -Body (@{ email = "you@example.com"; full_name = "You"; password = $password } | ConvertTo-Json)
$login = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/auth/login `
  -ContentType "application/json" -Body (@{ email = "you@example.com"; password = $password } | ConvertTo-Json)
$accessToken = $login.access_token
$headers = @{ Authorization = "Bearer $accessToken" }
$workspace = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/workspaces `
  -Headers $headers -ContentType "application/json" `
  -Body (@{ name = "Product" } | ConvertTo-Json)
$project = Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/workspaces/$($workspace.id)/projects" `
  -Headers $headers -ContentType "application/json" `
  -Body (@{ name = "Release"; description = "Release planning" } | ConvertTo-Json)
$projectId = $project.id
$body = @{
  project_id = $projectId
  title = "Prepare release notes"
  description = "Draft the release summary"
  priority = "high"
  due_date = "2026-12-01T09:00:00+07:00"
  assignee_id = $registered.id
} | ConvertTo-Json
$task = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/tasks `
  -Headers $headers -ContentType "application/json" -Body $body

# Task đã commit sẽ xếp email vào Mailpit: http://127.0.0.1:8025

Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/tasks?project_id=$projectId" -Headers $headers

# Kết hợp filter và lấy trang thứ hai (các filter dùng AND)
$assigneeId = "<UUID thành viên trong workspace>"
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/tasks?project_id=$projectId&status=todo&priority=high&assignee_id=$assigneeId&page=2&limit=20" `
  -Headers $headers

# Search không phân biệt hoa thường, kết hợp AND với các filter
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/tasks?project_id=$projectId&q=release&status=todo&page=1&limit=20" `
  -Headers $headers

Invoke-RestMethod -Method Patch -Uri "http://127.0.0.1:8000/api/v1/tasks/$($task.id)" `
  -Headers $headers -ContentType "application/json" -Body (@{ status = "done" } | ConvertTo-Json)

$label = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/labels `
  -Headers $headers -ContentType "application/json" `
  -Body (@{ project_id = $projectId; name = "Backend"; color = "blue" } | ConvertTo-Json)
Invoke-RestMethod -Method Put -Uri "http://127.0.0.1:8000/api/v1/tasks/$($task.id)/labels/$($label.id)" `
  -Headers $headers

$comment = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/tasks/$($task.id)/comments" `
  -Headers $headers -ContentType "application/json" `
  -Body (@{ content = "Ready for review" } | ConvertTo-Json)
Invoke-RestMethod -Method Patch -Uri "http://127.0.0.1:8000/api/v1/comments/$($comment.id)" `
  -Headers $headers -ContentType "application/json" `
  -Body (@{ content = "Reviewed" } | ConvertTo-Json)

# Search literal không phân biệt hoa thường; cache được bật khi dùng Compose
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/tasks?project_id=$projectId&q=release&page=1&limit=20" `
  -Headers $headers

Invoke-RestMethod -Method Delete -Uri "http://127.0.0.1:8000/api/v1/tasks/$($task.id)" -Headers $headers
```

## Cấu hình

Mọi biến môi trường dùng tiền tố `TASKHUB_`; các giá trị local mẫu nằm trong
`.env.example`:

| Biến                   | Giá trị mẫu |
| ---------------------- | ----------- |
| `TASKHUB_APP_NAME`     | `TaskHub`   |
| `TASKHUB_VERSION`      | `0.1.0`     |
| `TASKHUB_ENVIRONMENT`  | `local`     |
| `TASKHUB_DEBUG`        | `false`     |
| `TASKHUB_API_V1_PREFIX`| `/api/v1`   |
| `TASKHUB_HOST`         | `127.0.0.1` |
| `TASKHUB_PORT`         | `8000`      |
| `TASKHUB_DATABASE_URL` | `postgresql+asyncpg://postgres:taskhub@127.0.0.1:5433/taskhub` |
| `TASKHUB_DATABASE_PASSWORD` | optional for host development; Compose requires a private Postgres password |
| `TASKHUB_POSTGRES_PASSWORD` | required by full Compose; setup creates and stores a random value if blank |
| `TASKHUB_DATABASE_ECHO` | `false` |
| `TASKHUB_REDIS_URL` | `redis://127.0.0.1:6379/0` |
| `TASKHUB_JWT_SECRET_KEY` | bắt buộc, tối thiểu 32 bytes |
| `TASKHUB_ACCESS_TOKEN_MINUTES` | `15` |
| `TASKHUB_REFRESH_TOKEN_DAYS` | `30` |
| `TASKHUB_REFRESH_COOKIE_SECURE` | `true` (production bắt buộc) |
| `TASKHUB_REFRESH_COOKIE_SAMESITE` | `lax` |
| `TASKHUB_FRONTEND_ORIGINS` | `[]` (JSON list origin chính xác) |
| `TASKHUB_SMTP_HOST` | để trống thì tắt email; Compose dùng Mailpit nội bộ |
| `TASKHUB_SMTP_PORT` | `1025` |
| `TASKHUB_SMTP_FROM_EMAIL` | `no-reply@example.com` |
| `TASKHUB_SMTP_USERNAME` | trống hoặc username SMTP |
| `TASKHUB_SMTP_PASSWORD` | trống hoặc password; kiểu `SecretStr`, không trim secret |
| `TASKHUB_SMTP_STARTTLS` | `false` (Mailpit local không cần TLS) |
| `TASKHUB_SMTP_TIMEOUT_SECONDS` | `5` (lớn hơn 0 và tối đa 30) |

SMTP username và password phải cùng được đặt hoặc cùng để trống; nếu có thông tin
xác thực thì bắt buộc bật `TASKHUB_SMTP_STARTTLS=true`. SMTP host trống vô hiệu
hoá adapter email. API docs mô tả Bearer authentication và các response
lỗi; lỗi nghiệp vụ dùng `{ "detail": "..." }`, validation dùng `detail` dạng
danh sách. Full Compose chỉ gửi tới Mailpit local, không relay email ra ngoài.

## Kiểm thử database

Integration tests use coordinator-managed disposable test services, separate
from the persistent local application services in `compose.local.yaml`:
PostgreSQL container `taskhub-day5-db` exposes only `taskhub_test` on port 5432,
and Redis container `taskhub-day6-redis` is exposed on port 6380. Do not create a
test database in the local application PostgreSQL container. Run the suite with:

```powershell
$env:TASKHUB_TEST_DATABASE_URL = "postgresql+asyncpg://postgres:taskhub@127.0.0.1:5432/taskhub_test"
$env:TASKHUB_TEST_REDIS_URL = "redis://127.0.0.1:6380/0"
uv run python -m unittest discover -s tests -v
```

Kiểm tra tĩnh và unit tests không cần database:

```powershell
uv run ruff check app tests
uv run mypy app
uv run python -m unittest tests.test_project_api tests.test_project_service `
  tests.test_task_assignment_notifications tests.test_task_service
```

Test migration chạy `downgrade base` rồi `upgrade head`; sau test sẽ downgrade về `base`.
Không đặt `TASKHUB_TEST_DATABASE_URL` trỏ vào database ứng dụng.

### Cache task list

Đặt `TASKHUB_REDIS_URL=redis://localhost:6379/0` để bật Redis cache; URI
`redis://` và `rediss://` được hỗ trợ theo `RedisDsn` của Pydantic, gồm các mặc
định native như host `localhost` và database `/0`; có thể kèm credentials,
database index và query options. Runtime luôn ghi đè timeout, retry và giới hạn
pool bằng cấu hình ứng dụng. URI không hợp lệ làm settings validation thất bại
ngay khi khởi động. Bỏ trống để tắt. Cache lưu
snapshot JSON của task list trong 60 giây. Mỗi request vẫn đọc
database để xác thực và kiểm tra quyền project trước khi tra cache. Sau khi task
được tạo, sửa hoặc xóa và transaction commit thành công, service đổi generation
token của project; mọi filter và trang cũ trở nên không thể truy cập cùng lúc.
Lua compare-and-set ngăn một lần đọc bắt đầu trước invalidation ghi dữ liệu cũ
vào generation mới. Label/comment không làm đổi danh sách task nên không cần
invalidation.

Khi Redis lỗi, list đọc database và mutation đã commit vẫn thành công; cache
lookup/fill bị bỏ qua. Nếu rotation lỗi, snapshot cũ có thể được phục vụ cho tới
khi TTL 60 giây tính từ lần fill snapshot đó hết hạn. Một lần đọc đã chạy đồng
thời với mutation vẫn có thể fill snapshot sau commit nếu rotation thất bại;
vì vậy giới hạn 60 giây tính từ thời điểm fill, không phải từ thời điểm commit.
Cache không chứa quyền hoặc kết quả authorization. Redis client có socket/connect
timeout 0.5 giây, không retry command và được đóng khi app shutdown.

Để chạy kiểm thử Redis, đặt `TASKHUB_TEST_REDIS_URL` trỏ tới Redis riêng cho
test, ví dụ `redis://127.0.0.1:6380/0`, rồi chạy unittest. Bài test dùng namespace
ngẫu nhiên và chỉ xóa key thuộc namespace đó; không dùng `FLUSHDB`/`FLUSHALL`.
Kiểm thử kết hợp PostgreSQL/Redis cần đồng thời `TASKHUB_TEST_DATABASE_URL`
trỏ tới database disposable `taskhub_test` và `TASKHUB_TEST_REDIS_URL`.

## Cấu trúc

```
taskhub/
├── app/
│   ├── api/v1/
│   │   ├── router.py            # API v1 aggregation
│   │   ├── auth.py              # register/login/refresh/logout HTTP adapter
│   │   ├── users.py             # current-user HTTP adapter
│   │   ├── projects.py          # project HTTP adapter
│   │   └── tasks.py             # task HTTP adapter
│   ├── core/
│   │   ├── config.py            # Settings (env TASKHUB_*)
│   │   ├── deps.py              # request-scoped dependency wiring
│   │   ├── constants.py         # shared validation and error constants
│   │   ├── exceptions.py        # application/domain exceptions
│   │   └── security.py          # password hashing and JWT validation
│   ├── cache/                   # Redis adapters and validated cache snapshots
│   ├── db/                      # engine, metadata, seed, legacy utility
│   ├── models/                  # entities, enums, and task domain model
│   ├── notifications/           # SMTP transport and BackgroundTasks adapter
│   ├── repositories/            # SQL-only PostgreSQL persistence
│   ├── schemas/                 # Pydantic request, response, and shared types
│   ├── services/                # project/task/auth use cases and ports
│   └── main.py                  # app factory, middleware, exception handlers
├── alembic/versions/            # schema migrations
├── examples/                    # browser auth client and flow test
├── tests/                       # unit and PostgreSQL integration tests
├── Dockerfile
├── compose.yaml                 # full API/PostgreSQL/Redis/Mailpit stack
├── .dockerignore
├── pyproject.toml
├── .python-version
└── README.md
```

## Ghi chú thiết kế

- Repository SQLAlchemy async persist vào PostgreSQL; `InMemoryTaskRepository` vẫn có thể dùng trong unit test.
- Service không import FastAPI → dễ unit test, dễ tái sử dụng.
- `TaskNotFoundError` được dịch thành HTTP 404 tại composition root (`app/main.py`).
- API phân giải principal/HTTP; service điều phối transaction, cập nhật domain và dịch lỗi thiếu resource; policy thuần quyết định RBAC; repository scope query, khóa hàng và persist trong transaction.
- Workspace write khóa workspace rồi membership; lookup membership riêng giữ hỗ trợ owner legacy không có membership row và duy trì thứ tự khóa an toàn.
- Timestamp luôn timezone-aware UTC.
