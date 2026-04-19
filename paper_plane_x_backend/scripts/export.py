import argparse
import json
import shutil
import sqlite3
from pathlib import Path


def remove_citations(data):
    """
    递归遍历字典或列表，删除所有名为 'citations' 的键。
    这样不管 Pydantic 模型嵌套多深，都能精准剔除溯源文本。
    """
    if isinstance(data, dict):
        return {
            k: remove_citations(v)
            for k, v in data.items()
            if k != "citations"  # 核心逻辑：拦截 citations 键
        }
    elif isinstance(data, list):
        return [remove_citations(item) for item in data]
    else:
        return data


def try_parse_json(value):
    """尝试将数据库中的字符串解析为 JSON，如果失败则返回原字符串"""
    if not value:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


def export_landscape_data(db_path: str, output_name: str, export_dir: str):
    print(f"📦 Connecting to database: {db_path}...")

    if not Path(db_path).exists():
        print(f"❌ Error: Database file not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    # 让返回的结果行为像字典，可以通过列名访问
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # 查询所需的字段 (如果你的表没有 doi 字段，请在这里和下面代码中去掉)
        cursor.execute(
            """
            SELECT paper_id, title, authors, year, doi, raw_pdf_path, custom_meta, quick_scan, synthesis_data, analysis_report
            FROM papers
            WHERE extraction_status = 'COMPLETED' AND analysis_report IS NOT NULL
        """
        )
        rows = cursor.fetchall()

        exported_data = []

        for row in rows:
            # 基础元数据
            paper_item = {
                "paper_id": row["paper_id"],
                "title": row["title"],
                "authors": try_parse_json(row["authors"]),
                "year": row["year"],
                "doi": row["doi"],
                "raw_pdf_path": row["raw_pdf_path"],
                "custom_meta": try_parse_json(row["custom_meta"]),
            }

            # 解析并清理 quick_scan
            qs_data = try_parse_json(row["quick_scan"])
            paper_item["quick_scan"] = remove_citations(qs_data)

            # 解析并清理 synthesis_data (核心数据)
            sd_data = try_parse_json(row["synthesis_data"])
            paper_item["synthesis_data"] = remove_citations(sd_data)

            an_data = try_parse_json(row["analysis_report"])
            paper_item["analysis_report"] = remove_citations(an_data)

            exported_data.append(paper_item)

        print(f"✅ Successfully extracted {len(exported_data)} papers.")

        export_root = Path(export_dir)
        export_root.mkdir(parents=True, exist_ok=True)

        # 写入目标 JSON 文件（统一放在 export 目录下）
        output_file = export_root / Path(output_name).name

        with open(output_file, "w", encoding="utf-8") as f:
            # ensure_ascii=False 保证输出的是正常中文，而不是 \uXXXX
            json.dump(exported_data, f, ensure_ascii=False, indent=2)

        print(f"🎉 Data cleanly exported to: {output_file}")

        # 复制导出 JSON 中涉及到的 paper 文件夹到 export/data/papers/{paper_id}
        papers_source_root = Path(db_path).parent / "papers"
        papers_export_root = export_root / "data" / "papers"

        if papers_export_root.exists():
            shutil.rmtree(papers_export_root)
        papers_export_root.mkdir(parents=True, exist_ok=True)

        copied_count = 0
        missing_count = 0
        for item in exported_data:
            paper_id = item["paper_id"]
            source_dir = papers_source_root / paper_id
            target_dir = papers_export_root / paper_id

            if source_dir.exists() and source_dir.is_dir():
                shutil.copytree(source_dir, target_dir)
                copied_count += 1
            else:
                print(f"⚠️ Paper files not found for paper_id={paper_id}: {source_dir}")
                missing_count += 1

        print(
            "📁 Paper files export finished: "
            f"copied={copied_count}, missing={missing_count}, target={papers_export_root}"
        )

    except sqlite3.Error as e:
        print(f"❌ Database error: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Export paper data without citations and copy paper files."
    )
    # 默认值你可以修改为你的实际路径
    parser.add_argument(
        "--db",
        type=str,
        default="data/app.db",
        help="Path to SQLite database file",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="landscape_zd_data.json",
        help="Output JSON filename (will be placed under export directory)",
    )
    parser.add_argument(
        "--export-dir",
        type=str,
        default="export",
        help="Directory to store exported JSON and paper files",
    )

    args = parser.parse_args()
    export_landscape_data(args.db, args.out, args.export_dir)
