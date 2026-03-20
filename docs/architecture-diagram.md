# Charter Architecture — Complete System Diagram

## 1. End-to-End Pipeline

```mermaid
flowchart TB
    subgraph INPUT["📥 Input"]
        YAML["YAML Chart Spec<br/>(user-authored)"]
        MODEL_YAML["Model Manifest YAML<br/>(models/*.yaml)"]
        DATA_JSON["Inline JSON Data<br/>(*.json rows)"]
        CUBE_API["Cube.dev REST API<br/>(remote)"]
    end

    subgraph PARSE["Stage 1: Parse (src/schema/)"]
        parse_chart["parse_chart(yaml_string)<br/>→ ChartSpec"]
        chart_schema["chart_schema.py<br/>Pydantic validation"]
        parse_chart --> chart_schema
    end

    subgraph TRANSLATE["Stage 2: Translate (src/translator/)"]
        translate_chart["translate_chart(spec, models_dir?)<br/>→ VegaLiteSpec dict"]

        subgraph RESOLVER["Resolver Selection"]
            direction LR
            DR["DataBlockResolver<br/>(legacy DataSource)"]
            MR["ModelResolver<br/>(model name string)"]
        end

        subgraph ROUTER["Router (translate.py)"]
            direction TB
            route{"Shelf shape?"}
            route -->|"both shelves are strings"| single
            route -->|"one shelf is list"| stacked
            single["compile_single()"]
            stacked["compile_stacked()"]
            stacked -->|"any entry has .layer"| layers["compile_stacked_with_layers()<br/>⚠️ Phase 1a — NotImplementedError"]
        end

        subgraph HELPERS["Shared Helpers"]
            direction LR
            enc["encodings.py<br/>build_encodings()<br/>build_field_encoding()<br/>build_color/detail/size/tooltip()"]
            marks_mod["marks.py<br/>build_mark()"]
            filt["filters.py<br/>build_transforms()"]
            sort_mod["sort.py<br/>apply_sort()"]
        end

        facet_mod["facet.py<br/>apply_facet()"]
    end

    subgraph COMPOSE["Stage 3: Compose"]
        subgraph THEME["Theme (src/theme/)"]
            merge_theme["merge_theme(spec, theme?)<br/>Merges default_theme.json"]
        end
        subgraph DATA["Data (src/data/)"]
            resolve_data["resolve_data(spec, chart_spec, rows?)"]
            bind_data["bind_data(spec, rows)"]
            cube_client["cube_client.py<br/>fetch_from_cube()"]
        end
        subgraph RENDER["Render (src/render/)"]
            render_html["render_html(spec, title?)<br/>→ HTML string"]
        end
    end

    subgraph OUTPUT["📤 Output"]
        HTML["Standalone HTML<br/>(Vega-Lite + vegaEmbed CDN)"]
    end

    subgraph CLI["CLI Entry Points (src/cli/)"]
        cli_render["render.py<br/>Static file output"]
        cli_dev["dev.py<br/>Live-reload dev server<br/>(port 8089)"]
    end

    %% Main flow
    YAML --> parse_chart
    chart_schema --> translate_chart
    MODEL_YAML -.->|"load_model()"| MR
    translate_chart --> RESOLVER
    RESOLVER --> ROUTER
    single --> HELPERS
    stacked --> HELPERS
    ROUTER --> facet_mod
    facet_mod --> merge_theme
    merge_theme --> resolve_data
    DATA_JSON -.->|"inline rows"| bind_data
    CUBE_API -.->|"HTTP POST"| cube_client
    resolve_data --> bind_data
    resolve_data --> cube_client
    resolve_data --> render_html
    render_html --> HTML

    CLI --> parse_chart
    cli_render --> HTML
    cli_dev --> HTML

    style INPUT fill:#e8f4f8,stroke:#2196F3
    style PARSE fill:#fff3e0,stroke:#FF9800
    style TRANSLATE fill:#f3e5f5,stroke:#9C27B0
    style COMPOSE fill:#e8f5e9,stroke:#4CAF50
    style OUTPUT fill:#fce4ec,stroke:#E91E63
    style CLI fill:#f5f5f5,stroke:#607D8B
```

## 2. Pydantic Model Hierarchy (ChartSpec)

```mermaid
classDiagram
    class ChartSpec {
        +str|None version
        +str sheet
        +str|None description
        +DataSpec data
        +ShelfSpec|None cols
        +ShelfSpec|None rows
        +MarkSpec|None marks
        +ColorSpec|None color
        +str|None detail
        +str|int|float|None size
        +TooltipSpec|None tooltip
        +list~ShelfFilter~|None filters
        +SortSpec|None sort
        +FacetSpec|None facet
        +AxisConfig|None axis
        +KPIConfig|None kpi
        +validate: at_most_one_multi_measure_shelf()
        +validate: single_measure_requires_marks()
    }

    class DataSpec {
        <<Union>>
        str | DataSource
    }

    class DataSource {
        +str model
        +list~str~ measures
        +list~str~ dimensions
        +TimeGrainConfig|None time_grain
    }

    class TimeGrainConfig {
        +str field
        +TimeGrain grain
    }

    class ShelfSpec {
        <<Union>>
        str | list~MeasureEntry~
    }

    class MeasureEntry {
        +str measure
        +MarkSpec|None mark
        +ColorSpec|None color
        +str|None detail
        +str|int|float|None size
        +float|None opacity
        +list~LayerEntry~|None layer
        +ScaleResolve|None axis
    }

    class LayerEntry {
        +str measure
        +MarkSpec|None mark
        +ColorSpec|None color
        +str|None detail
        +str|int|float|None size
        +float|None opacity
    }

    class MarkSpec {
        <<Union>>
        MarkType | MarkObject
    }

    class MarkObject {
        +MarkType type
        +str|None style
        +bool|None point
        +float|None opacity
    }

    class ColorSpec {
        <<Union>>
        str | ColorFieldMapping
    }

    class ColorFieldMapping {
        +str field
        +str|None type
    }

    class ShelfFilter {
        +str field
        +FilterOperator operator
        +str|int|float|None value
        +list|None values
        +list|None range
        +validate: _validate_operator_and_values()
    }

    class SortSpec {
        <<Union>>
        FieldSort | AxisSort
    }

    class FieldSort {
        +str field
        +SortOrder|list~str~ order
        +str channel = "x"
    }

    class AxisSort {
        +str axis
        +SortOrder order
        +str channel = "x"
    }

    class FacetSpec {
        <<Union>>
        WrapFacet | RowColumnFacet
    }

    class WrapFacet {
        +str field
        +int columns
        +SortOrder|None sort
        +ScaleResolve|None axis
    }

    class RowColumnFacet {
        +str|None row
        +str|None column
        +ScaleResolve|None axis
    }

    class AxisConfig {
        +AxisChannelConfig|None x
        +AxisChannelConfig|None y
    }

    class AxisChannelConfig {
        +str|None title
        +str|None format
        +bool|None grid
    }

    class KPIConfig {
        +str measure
        +str|None format
        +KPIComparison|None comparison
    }

    ChartSpec --> DataSpec
    ChartSpec --> ShelfSpec : rows, cols
    ChartSpec --> MarkSpec : marks
    ChartSpec --> ColorSpec : color
    ChartSpec --> ShelfFilter : filters
    ChartSpec --> SortSpec : sort
    ChartSpec --> FacetSpec : facet
    ChartSpec --> AxisConfig : axis
    ChartSpec --> KPIConfig : kpi
    DataSpec --> DataSource
    DataSource --> TimeGrainConfig
    ShelfSpec --> MeasureEntry
    MeasureEntry --> LayerEntry : layer (Phase 1a)
    MeasureEntry --> MarkSpec : mark
    MeasureEntry --> ColorSpec : color
    MarkSpec --> MarkObject
    ColorSpec --> ColorFieldMapping
    SortSpec --> FieldSort
    SortSpec --> AxisSort
    FacetSpec --> WrapFacet
    FacetSpec --> RowColumnFacet
    AxisConfig --> AxisChannelConfig
```

## 3. Data Model Manifest Schema (src/models/)

```mermaid
classDiagram
    class DataModel {
        +str model
        +str label
        +str|None description
        +ModelSource|None source
        +dict~str, MeasureDefinition~ measures
        +dict~str, DimensionDefinition~ dimensions
        +validate: measures_not_empty()
    }

    class MeasureDefinition {
        +str label
        +str|None format
        +str|None description
        +SortOrder|None defaultSort
        +str|None aggregation
    }

    class DimensionDefinition {
        <<Union>>
        TemporalDimensionDefinition | NominalDimensionDefinition
    }

    class NominalDimensionDefinition {
        +str type = "nominal"|"ordinal"
        +str label
        +str|None description
        +SortOrder|None defaultSort
        +list~str~|None sortOrder
    }

    class TemporalDimensionDefinition {
        +Literal~temporal~ type
        +str label
        +str|None description
        +list~TimeGrain~ grains
        +TimeGrain defaultGrain
        +dict~str,str~|None format
    }

    class ModelSource {
        <<Union>>
        InlineSource | CubeSource
    }

    class InlineSource {
        +Literal~inline~ type
        +str path
    }

    class CubeSource {
        +Literal~cube~ type
        +str cube
    }

    DataModel --> MeasureDefinition : measures
    DataModel --> DimensionDefinition : dimensions
    DataModel --> ModelSource : source
    DimensionDefinition --> TemporalDimensionDefinition
    DimensionDefinition --> NominalDimensionDefinition
    ModelSource --> InlineSource
    ModelSource --> CubeSource
```

## 4. Field Type Resolver Pattern (Protocol)

```mermaid
classDiagram
    class FieldTypeResolver {
        <<Protocol>>
        +resolve(field_name: str) VegaLiteType
        +resolve_base_field(field_ref: str) str
        +resolve_time_unit(field_ref: str) str|None
        +resolve_format(field_ref: str) str|None
    }

    class DataBlockResolver {
        -DataSource data
        -set measures
        -set dimensions
        -str|None temporal_field
        +resolve(field_name) VegaLiteType
        +resolve_base_field(field_ref) str
        +resolve_time_unit(field_ref) None
        +resolve_format(field_ref) None
    }

    class ModelResolver {
        -DataModel model
        -dict|None formulas
        +resolve(field_name) VegaLiteType
        +resolve_type(field_ref) VegaLiteType
        +resolve_label(field_ref) str
        +resolve_format(field_ref) str|None
        +resolve_time_unit(field_ref) str|None
        +resolve_base_field(field_ref) str
        +resolve_default_sort(field_ref) str|None
        +resolve_sort_order(field_ref) list|None
        +is_measure(field_ref) bool
        +is_dimension(field_ref) bool
        -_parse_field_ref(ref) tuple
        -_lookup(ref) tuple
    }

    FieldTypeResolver <|.. DataBlockResolver : implements
    FieldTypeResolver <|.. ModelResolver : implements

    note for DataBlockResolver "Phase 1: Types from ChartSpec\ndata block (measures/dimensions)"
    note for ModelResolver "Phase 3: Types + labels + formats\n+ time units from DataModel YAML.\nSupports dot notation:\norder_date.month → temporal + yearmonth"
```

## 5. Translation Routing Decision Tree

```mermaid
flowchart TD
    START["translate_chart(spec)"] --> RESOLVE_DATA{"spec.data type?"}

    RESOLVE_DATA -->|"string (model name)"| LOAD_MODEL["load_model(name, models_dir)<br/>→ DataModel"]
    LOAD_MODEL --> CREATE_MR["ModelResolver(model)"]

    RESOLVE_DATA -->|"DataSource object"| CREATE_DBR["DataBlockResolver(data)"]

    CREATE_MR --> ROUTE
    CREATE_DBR --> ROUTE

    ROUTE{"Shelf shape?"}

    ROUTE -->|"rows: str, cols: str<br/>(both simple fields)"| SINGLE["compile_single(spec, resolver)"]

    ROUTE -->|"rows: list[MeasureEntry]<br/>OR cols: list[MeasureEntry]"| STACKED["compile_stacked(spec, resolver)"]

    SINGLE --> S_MARK["build_mark(spec.marks)"]
    SINGLE --> S_ENC["build_encodings(spec, resolver)<br/>→ x, y, color, detail, size, tooltip"]
    SINGLE --> S_SORT["apply_sort(encoding, spec.sort)"]
    SINGLE --> S_FILT["build_transforms(spec.filters)"]
    S_MARK --> SINGLE_OUT["{mark, encoding, transform?}"]
    S_ENC --> SINGLE_OUT
    S_SORT --> SINGLE_OUT
    S_FILT --> SINGLE_OUT

    STACKED --> HAS_LAYERS{"Any entry<br/>has .layer?"}

    HAS_LAYERS -->|Yes| LAYERS["compile_stacked_with_layers()<br/>⚠️ raises NotImplementedError"]

    HAS_LAYERS -->|No| SAME_MARK{"All entries<br/>same mark?<br/>No per-entry<br/>color/detail?"}

    SAME_MARK -->|Yes| REPEAT["_compile_repeat()<br/>→ {repeat: {row: [fields]}, spec: ...}"]
    SAME_MARK -->|No| CONCAT["_compile_concat()<br/>→ {vconcat/hconcat: [...panels]}"]

    SINGLE_OUT --> FACET
    REPEAT --> FACET
    CONCAT --> FACET

    FACET["apply_facet(inner, spec.facet)"]

    FACET --> HAS_FACET{"spec.facet?"}
    HAS_FACET -->|None| FINAL["Add $schema<br/>Return VL spec"]
    HAS_FACET -->|WrapFacet| WRAP["{facet: {field, type}, columns: N, spec: inner}"]
    HAS_FACET -->|RowColumnFacet| RC["{facet: {row?, column?}, spec: inner}"]
    WRAP --> FINAL
    RC --> FINAL

    style LAYERS fill:#ffcdd2,stroke:#e53935
    style FINAL fill:#c8e6c9,stroke:#43a047
```

## 6. Encoding Builder Detail

```mermaid
flowchart LR
    subgraph build_encodings["build_encodings(spec, resolver)"]
        direction TB

        X["x: build_field_encoding(cols, resolver)<br/>+ axis config"]
        Y["y: build_field_encoding(rows, resolver)<br/>+ axis config + auto-format"]

        COLOR{"spec.color?"}
        COLOR -->|hex string| CV["color: {value: '#hex'}"]
        COLOR -->|field name| CF["color: build_field_encoding(field)"]
        COLOR -->|ColorFieldMapping| CM["color: {field, type}"]

        DETAIL{"spec.detail?"} --> DF["detail: build_field_encoding(field)"]

        SIZE{"spec.size?"}
        SIZE -->|number| SV["size: {value: N}"]
        SIZE -->|field name| SF["size: build_field_encoding(field)"]

        TOOLTIP{"spec.tooltip?"} --> TF["tooltip: [field encodings...]"]
    end

    subgraph build_field_encoding["build_field_encoding(field_ref, resolver)"]
        direction TB
        BFE_IN["field_ref: 'revenue' or 'order_date.month'"]
        BFE_BASE["resolver.resolve_base_field(ref)<br/>→ strip grain suffix"]
        BFE_TYPE["resolver.resolve(ref)<br/>→ quantitative|temporal|nominal"]
        BFE_TU["resolver.resolve_time_unit(ref)<br/>→ 'yearmonth' or None"]
        BFE_OUT["{field: 'order_date',<br/> type: 'temporal',<br/> timeUnit: 'yearmonth'}"]
        BFE_IN --> BFE_BASE --> BFE_TYPE --> BFE_TU --> BFE_OUT
    end
```

## 7. Data Resolution Flow

```mermaid
flowchart TD
    RD["resolve_data(vl_spec, chart_spec, rows?)"]

    RD --> HAS_ROWS{"rows provided?"}

    HAS_ROWS -->|Yes| BIND["bind_data(spec, rows)<br/>spec['data'] = {values: rows}"]

    HAS_ROWS -->|No| DATA_TYPE{"chart_spec.data type?"}

    DATA_TYPE -->|"string (model name)"| LOAD["load_model(name)"]
    LOAD --> SOURCE{"model.source type?"}
    SOURCE -->|CubeSource| CUBE_MODEL["fetch_from_cube_model(model, filters)"]
    SOURCE -->|InlineSource| INLINE["Load JSON from path"]
    SOURCE -->|None| ERR1["ValueError"]

    DATA_TYPE -->|DataSource| CUBE_LEGACY["fetch_from_cube(data, filters)"]

    subgraph CUBE["Cube.dev Client (cube_client.py)"]
        direction TB
        BUILD_Q["build_cube_query(data, filters)<br/>→ prefix fields with model name<br/>→ translate filters"]
        POST["POST /cubejs-api/v1/load<br/>Authorization: api_token"]
        STRIP["_strip_prefix(row)<br/>'Orders.revenue' → 'revenue'"]
        BUILD_Q --> POST --> STRIP
    end

    CUBE_MODEL --> CUBE
    CUBE_LEGACY --> CUBE

    CUBE --> BIND
    INLINE --> BIND

    BIND --> DONE["VL spec with data.values attached"]

    style CUBE fill:#e3f2fd,stroke:#1976D2
```

## 8. Inheritance Chain (Multi-Measure)

```mermaid
flowchart TD
    subgraph TOP["Top-Level ChartSpec"]
        T_MARKS["marks: line"]
        T_COLOR["color: country"]
        T_DETAIL["detail: null"]
    end

    subgraph ENTRY["MeasureEntry (rows[0])"]
        E_MARK["mark: bar ← overrides 'line'"]
        E_COLOR["color: null ← inherits 'country'"]
        E_DETAIL["detail: null ← inherits null"]
    end

    subgraph LAYER["LayerEntry (rows[0].layer[0]) — Phase 1a"]
        L_MARK["mark: {type: line, style: dashed} ← overrides 'bar'"]
        L_COLOR["color: '#666666' ← overrides 'country'"]
        L_DETAIL["detail: null ← inherits null"]
    end

    TOP -->|"fallback"| ENTRY
    ENTRY -->|"fallback"| LAYER

    style TOP fill:#e8eaf6,stroke:#3F51B5
    style ENTRY fill:#f3e5f5,stroke:#9C27B0
    style LAYER fill:#fce4ec,stroke:#E91E63
```

## 9. CLI Entry Points

```mermaid
flowchart LR
    subgraph render_cli["src/cli/render.py — Static Output"]
        R1["Parse args:<br/>yaml_path, --data, --out,<br/>--no-theme, --no-data"]
        R2["parse_chart()"]
        R3["translate_chart()"]
        R4["merge_theme()"]
        R5["resolve_data()"]
        R6["render_html()"]
        R7["Write .html file"]
        R1 --> R2 --> R3 --> R4 --> R5 --> R6 --> R7
    end

    subgraph dev_cli["src/cli/dev.py — Live Reload Server"]
        D1["Parse args:<br/>yaml_path, --data,<br/>--port, --no-theme"]
        D2["_build() — full pipeline"]
        D3["_YAMLWatcher<br/>(FileSystemEventHandler)"]
        D4["HTTP Server<br/>GET / → HTML<br/>GET /__timestamp → reload check"]
        D5["Auto-reload JS<br/>polls every 500ms"]
        D1 --> D2
        D3 -->|"on_modified"| D2
        D2 --> D4
        D4 --> D5
    end
```

## 10. Module Dependency Map

```mermaid
graph TD
    subgraph PUBLIC_API["src/__init__.py (Public API)"]
        API["parse_chart · translate_chart · merge_theme<br/>bind_data · resolve_data · render_html<br/>ChartSpec · DSL_VERSION"]
    end

    subgraph SCHEMA["src/schema/"]
        CS["chart_schema.py<br/>ChartSpec, parse_chart"]
        FT["field_types.py<br/>DataBlockResolver"]
    end

    subgraph MODELS["src/models/"]
        MS["schema.py<br/>DataModel"]
        ML["loader.py<br/>load_model"]
        MRR["resolver.py<br/>ModelResolver"]
    end

    subgraph TRANSLATOR["src/translator/"]
        TR["translate.py<br/>translate_chart"]
        ENC["encodings.py"]
        MK["marks.py"]
        FL["filters.py"]
        SR["sort.py"]
        FC["facet.py"]
        PS["patterns/single.py"]
        PST["patterns/stacked.py"]
        PL["patterns/layers.py"]
    end

    subgraph THEME["src/theme/"]
        TM["merge.py"]
        TJ["default_theme.json"]
    end

    subgraph DATA_MOD["src/data/"]
        BD["bind.py<br/>bind_data, resolve_data"]
        CC["cube_client.py"]
    end

    subgraph RENDER_MOD["src/render/"]
        RH["to_html.py"]
    end

    %% Dependencies
    TR --> CS
    TR --> FT
    TR --> ML
    TR --> MRR
    TR --> PS
    TR --> PST
    TR --> FC
    PS --> ENC
    PS --> MK
    PS --> FL
    PS --> SR
    PST --> ENC
    PST --> MK
    PST --> FL
    PST --> PL
    ENC --> FT
    ENC --> MRR
    BD --> CC
    BD --> ML
    TM --> TJ
    MRR --> MS
    ML --> MS

    API --> CS
    API --> TR
    API --> TM
    API --> BD
    API --> RH

    style PUBLIC_API fill:#e8f5e9,stroke:#4CAF50
    style SCHEMA fill:#fff3e0,stroke:#FF9800
    style MODELS fill:#e1f5fe,stroke:#03A9F4
    style TRANSLATOR fill:#f3e5f5,stroke:#9C27B0
    style THEME fill:#f1f8e9,stroke:#8BC34A
    style DATA_MOD fill:#e3f2fd,stroke:#2196F3
    style RENDER_MOD fill:#fce4ec,stroke:#E91E63
```
