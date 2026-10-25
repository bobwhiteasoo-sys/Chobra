#!/bin/sh
set -eu
psql --username "$POSTGRES_USER" --dbname postgres --set=owner_password="$CHOBRA_OWNER_PASSWORD" --set=app_password="$CHOBRA_APP_PASSWORD" <<'SQL'
CREATE ROLE chobra_owner LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD :'owner_password';
CREATE ROLE chobra_app LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD :'app_password';
CREATE DATABASE chobra OWNER chobra_owner;
SQL
