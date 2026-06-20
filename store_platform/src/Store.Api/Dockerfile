# syntax=docker/dockerfile:1
#
# Store.Api production image.
#
# IMPORTANT: the build context MUST be store_platform/ (not src/Store.Api), because the build
# reaches Directory.*.props, nuget.config, the VENDORED Crux feed in local-feed/, and the
# Store.Catalog project. Deploy with (run from store_platform/):
#   fly deploy --config deploy/fly/api.fly.toml
# The fly.toml points [build].dockerfile at this file with context = store_platform/.
# Plain Docker equivalent:
#   docker build -f src/Store.Api/Dockerfile -t store-api .

FROM mcr.microsoft.com/dotnet/sdk:9.0 AS build
WORKDIR /src

# Restore layer first, so editing source does not bust the NuGet cache. Crux.* resolve from the
# vendored local-feed/ (see nuget.config) — no private/GitHub feed or network token needed.
COPY nuget.config Directory.Build.props Directory.Packages.props ./
COPY local-feed/ ./local-feed/
COPY src/Store.Api/Store.Api.csproj src/Store.Api/
COPY src/Store.Catalog/Store.Catalog.csproj src/Store.Catalog/
RUN dotnet restore src/Store.Api/Store.Api.csproj

# Build + publish.
COPY src/Store.Api/ src/Store.Api/
COPY src/Store.Catalog/ src/Store.Catalog/
RUN dotnet publish src/Store.Api/Store.Api.csproj -c Release -o /app --no-restore

FROM mcr.microsoft.com/dotnet/aspnet:9.0 AS runtime
WORKDIR /app

# Listen on 8080 (Fly's default internal_port). The SQLite catalogue/orders db lives on a
# mounted persistent volume at /data — NEVER in the image (it would reset on every deploy).
# Production env makes MoneyRailConfigGate fail-closed: a missing/placeholder secret refuses
# boot instead of taking money it cannot fulfil.
ENV ASPNETCORE_URLS=http://+:8080 \
    ASPNETCORE_ENVIRONMENT=Production \
    ConnectionStrings__DefaultConnection="Data Source=/data/store.db"
RUN mkdir -p /data
COPY --from=build /app ./
EXPOSE 8080
ENTRYPOINT ["dotnet", "Store.Api.dll"]
