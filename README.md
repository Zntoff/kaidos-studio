# Kaidos Studio

Repositorio de la aplicación Kaidos Studio.

## Stages

- `dev`: rama para el desarrollo y la integración de cambios.
- `main`: rama de producción. Integra los cambios aprobados desde `dev`.

El repositorio es público, así que el código de ambas ramas también es público.

## Releases

Las versiones de producción usan tags semánticos con el prefijo `v` (`vMAJOR.MINOR.PATCH`). Al subir un tag como `v1.0.0`, GitHub Actions crea un GitHub Release público con notas generadas automáticamente.

```bash
git checkout main
git pull origin main
git tag v1.0.0
git push origin v1.0.0
```
