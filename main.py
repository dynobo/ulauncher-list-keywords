import json
import logging
import os
import pickle
from dataclasses import dataclass
from pathlib import Path

# pyright: reportMissingImports=false
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.client.Extension import Extension
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.action.SetUserQueryAction import SetUserQueryAction
from ulauncher.api.shared.event import KeywordQueryEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.item.ExtensionSmallResultItem import ExtensionSmallResultItem

logger = logging.getLogger(__name__)

CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path().home() / ".config"))
CONFIG_PATH = CONFIG_HOME / "ulauncher"
PREFS_PATH = CONFIG_PATH / "ext_preferences"
DATA_HOME = Path(os.environ.get("XDG_DATA_HOME", Path().home() / ".local" / "share"))
EXTENSIONS_PATH = DATA_HOME / "ulauncher" / "extensions"


@dataclass
class Keyword:
    """Encapsulates information about a single keyword."""

    name: str  # Extension name
    description: str  # Extension description
    icon: str  # Extension icon
    ext_keywords_count: int  # Number of keywords for this extension
    keyword_idx: int  # Index of keyword (when multiple are provided)
    keyword: str  # Trigger keyword
    keyword_desc: str = ""  # Description of keyword (if provided)

    @property
    def query(self):
        """String used for filtering if user types a query."""
        return "  ".join(
            [self.name, self.description, self.keyword, self.keyword_desc]
        ).lower()

    @property
    def is_placeholder(self):
        """Indicator for placeholder items."""
        return self.keyword_idx < 0

    def to_item(self, own_keyword, compact: bool = False):
        """Convert this keyword to a Ulauncher result item instance."""
        view_more_text = "Select to view keywords ..."

        if compact:
            result_class = ExtensionSmallResultItem
            keyword = self.name if self.is_placeholder else self.keyword
            extension_name = view_more_text if self.is_placeholder else self.name
            name = f"{keyword}  →  {extension_name}"
            description = ""
        else:
            result_class = ExtensionResultItem
            name = self.name if self.is_placeholder else self.keyword
            description = (
                f"{self.name} - {self.keyword_desc}" if self.keyword_desc else self.name
            )
            description = view_more_text if self.is_placeholder else description

        if self.is_placeholder:
            action = SetUserQueryAction(f"{own_keyword} {self.name} ")
        else:
            action = SetUserQueryAction(self.keyword + " ")

        return result_class(
            icon=self.icon,
            name=name,
            description=description,
            on_enter=action,
        )


class ListKeywordsExtension(Extension):
    def __init__(self):
        super().__init__()
        self.extensions_data = self.get_extensions_data()
        self.shortcuts_data = self.get_shortcuts_data()
        self.subscribe(KeywordQueryEvent, KeywordQueryEventListener())

    @staticmethod
    def get_shortcuts_data():
        with open(CONFIG_PATH / "shortcuts.json", "r", encoding="utf8") as fh:
            shortcuts = json.load(fh)

        return [
            Keyword(
                ext_keywords_count=1,
                name=s["name"],
                description="Shortcut",
                icon=s["icon"],
                keyword=s["keyword"],
                keyword_idx=0,
            )
            for s in shortcuts.values()
        ]

    @staticmethod
    def get_extensions_data():
        extension_keywords = []
        for manifest_file in EXTENSIONS_PATH.glob("**/manifest.json"):
            with open(manifest_file, "r", encoding="utf8") as fh:
                manifest = json.load(fh)

            extension_id = manifest_file.parent.name

            if extension_id == "com.github.dynobo.ulauncher-list-keywords":
                continue

            # Extension keywords with default values, as provided in manifest.json
            keyword_prefs = [
                p for p in manifest["preferences"] if p["type"] == "keyword"
            ]

            # Extension preferences, as adjusted by user
            with open(PREFS_PATH / f"{extension_id}.db", "rb") as fh:
                extension_prefs = pickle.load(fh)

            for idx, keyword_pref in enumerate(keyword_prefs):
                # Update default keyword value from user preferences
                keyword_pref["value"] = extension_prefs.get(
                    keyword_pref["id"], keyword_pref["default_value"]
                )

                icon = str((manifest_file.parent / manifest["icon"]).resolve())

                extension_keywords.append(
                    Keyword(
                        ext_keywords_count=len(keyword_prefs),
                        name=manifest["name"],
                        description="Shortcut",
                        icon=icon,
                        keyword=keyword_pref.get("value", ""),
                        keyword_desc=keyword_pref.get("description", ""),
                        keyword_idx=idx,
                    )
                )

                if idx == 0 and len(keyword_prefs) > 1:
                    # Add one placeholder entry for extensions with mulitple keywords
                    extension_keywords.append(
                        Keyword(
                            ext_keywords_count=1,
                            name=manifest["name"],
                            description="",
                            icon=icon,
                            keyword="",
                            keyword_desc="",
                            keyword_idx=-1,  # this marks the keyword as placeholder!
                        )
                    )
        return extension_keywords

    def get_keywords(self):
        if self.preferences.get("include_shortcuts", "True") == "True":
            return self.extensions_data + self.shortcuts_data
        return self.extensions_data


class KeywordQueryEventListener(EventListener):
    def on_event(self, event, extension):
        query = event.get_argument()
        query = query.lower() if query else query

        multiple_mode = extension.preferences.get("multiple_mode", "collapse")
        is_compact = extension.preferences.get("item_style", "normal") == "compact"
        max_results = int(extension.preferences.get("max_results", 8))
        max_results = max_results * 2 if is_compact else max_results

        keywords = extension.get_keywords()

        if multiple_mode == "show_first":
            keywords = [k for k in keywords if k.keyword_idx == 0]
        elif multiple_mode == "collapse" and not query:
            keywords = [
                k for k in keywords if k.is_placeholder or k.ext_keywords_count == 1
            ]
        else:
            keywords = [k for k in keywords if not k.is_placeholder]

        # Filter by query
        if query:
            keywords = [k for k in keywords if query in k.query]

        # Sort results
        keywords.sort(key=lambda k: k.name + k.description)

        # Limit number of results
        keywords = keywords[:max_results]

        # Convert to result item instances
        own_keyword = event.get_keyword()
        items = [k.to_item(own_keyword, compact=is_compact) for k in keywords]

        return RenderResultListAction(items)


if __name__ == "__main__":
    ListKeywordsExtension().run()
