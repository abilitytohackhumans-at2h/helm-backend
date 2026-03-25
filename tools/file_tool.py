import os

async def file_create(filename: str, content: str) -> str:
    """Crea un archivo con el contenido dado."""
    output_dir = "outputs"
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Archivo creado: {filepath}"

FILE_CREATE_TOOL = {
    "name": "file_create",
    "description": "Crea un archivo con el contenido especificado. Util para guardar informes, documentos, y otros outputs.",
    "input_schema": {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Nombre del archivo (ej: informe.md)"
            },
            "content": {
                "type": "string",
                "description": "Contenido del archivo"
            }
        },
        "required": ["filename", "content"]
    }
}
