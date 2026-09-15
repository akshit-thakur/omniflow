import { useState } from 'react'
import { Icon } from '../components/Icon'
import { relationships, schemaFeatures, tables, type TableDefinition } from '../data/databaseMap'

const diagramGroups = ['Planning', 'Medication', 'Training', 'Kitchen', 'Media', 'AI & audit'] as const

const runtimeJourneys = [
  {
    id: 'crud',
    label: 'Page or form',
    summary: 'The normal path. The API validates the request, PostgreSQL enforces the durable rules, and React Query refreshes the view.',
    steps: [
      ['React SPA', 'page and typed form'],
      ['Nginx', 'single public origin'],
      ['FastAPI', 'Pydantic and router'],
      ['PostgreSQL', 'transaction and constraints'],
    ],
  },
  {
    id: 'ai-read',
    label: 'Assistant read',
    summary: 'The AI service embeds the question, fuses lexical and vector results, and gives only bounded context to the reasoner.',
    steps: [
      ['API AI proxy', 'private service secret'],
      ['AI service', 'retrieval orchestration'],
      ['bge-m3 + pgvector', 'hybrid context'],
      ['qwen3:8b', 'grounded answer'],
    ],
  },
  {
    id: 'ai-write',
    label: 'Assistant write',
    summary: 'The model proposes allowlisted actions. The API resolves and validates them, then commits domain rows and audit rows together.',
    steps: [
      ['AI planner', 'typed actions only'],
      ['Internal API', 'secret and schema check'],
      ['Mutation executor', 'ordered transaction'],
      ['Domain + audit', 'commit or full rollback'],
    ],
  },
] as const

type ColumnFlagName = NonNullable<TableDefinition['columns'][number]['flags']>[number]

function ColumnFlag({ flag }: { flag: Exclude<ColumnFlagName, 'FK'> }) {
  return <span className={`db-flag db-flag-${flag.toLowerCase()}`}>{flag}</span>
}

function TableDetail({ table }: { table: TableDefinition }) {
  const parents = relationships.filter((relationship) => relationship.from === table.name)
  const children = relationships.filter((relationship) => relationship.to === table.name)
  const columnRelationship = (columnName: string) => parents.find((relationship) => relationship.fromColumn === columnName)

  return (
    <section className="db-detail-panel" aria-live="polite">
      <div className="db-detail-heading">
        <div>
          <p className="eyebrow">{table.group}</p>
          <h2>{table.name}</h2>
          <p>{table.purpose}</p>
        </div>
      </div>

      <h3>Columns</h3>
      <div className="db-columns" role="table" aria-label={`${table.name} columns`}>
        {table.columns.map((column) => (
          <div className="db-column" role="row" key={column.name}>
            <code role="cell">{column.name}</code>
            <span role="cell">{column.type}</span>
            <span className="db-column-flags" role="cell">
              {column.flags?.filter((flag) => flag !== 'FK').map((flag) => <ColumnFlag key={flag} flag={flag} />)}
            </span>
            <span className="db-column-detail" role="cell">
              {columnRelationship(column.name)?.meaning ?? column.detail ?? ''}
            </span>
          </div>
        ))}
      </div>

      <div className="db-detail-grid">
        <div className="db-fk-card">
          <h3>Foreign keys</h3>
          {parents.length || children.length ? <>
            {parents.length ? <div className="db-fk-section">
              <strong>Depends on</strong>
              <ul className="db-list">
                {parents.map((relationship) => (
                  <li key={`${relationship.from}.${relationship.fromColumn}`}>
                    <code>{relationship.from}.{relationship.fromColumn}</code> <span>references</span> <code>{relationship.to}.{relationship.toColumn}</code>
                    <span>{relationship.meaning} {relationship.nullable ? 'Nullable.' : 'Required.'} On delete: {relationship.onDelete}.</span>
                  </li>
                ))}
              </ul>
            </div> : null}
            {children.length ? <div className="db-fk-section">
              <strong>Referenced by</strong>
              <ul className="db-list">
                {children.map((relationship) => (
                  <li key={`${relationship.from}.${relationship.fromColumn}`}>
                    <code>{relationship.from}.{relationship.fromColumn}</code> <span>references</span> <code>{relationship.to}.{relationship.toColumn}</code>
                    <span>{relationship.meaning} {relationship.nullable ? 'Nullable child link.' : 'Required child link.'} On delete: {relationship.onDelete}.</span>
                  </li>
                ))}
              </ul>
            </div> : null}
          </> : <p className="db-empty-copy">No enforced foreign keys. This table is standalone, derived, or connected by logical descriptors.</p>}
        </div>
        <div>
          <h3>Indexes & constraints</h3>
          <ul className="db-list db-list-tight">{table.indexes.map((index) => <li key={index}><code>{index}</code></li>)}</ul>
        </div>
      </div>

      <div className="db-detail-grid">
        <div>
          <h3>Application usage</h3>
          <dl className="db-usage">
            <dt>Writes</dt><dd>{table.usage.writes.join('; ')}</dd>
            <dt>Reads</dt><dd>{table.usage.reads.join('; ')}</dd>
            <dt>Routes</dt><dd>{table.usage.routes.join('; ')}</dd>
            <dt>Consumers</dt><dd>{table.usage.consumers.join('; ')}</dd>
          </dl>
        </div>
        <div>
          <h3>Lifecycle</h3>
          <p>{table.usage.lifecycle ?? 'Current schema table.'}</p>
        </div>
      </div>
    </section>
  )
}

function RelationshipNeighborhood({ table, onSelect }: { table: TableDefinition; onSelect: (name: string) => void }) {
  const parents = relationships.filter((relationship) => relationship.from === table.name)
  const children = relationships.filter((relationship) => relationship.to === table.name)

  const relationNode = (name: string, detail: string, onSelect: () => void) => (
    <button type="button" className="db-neighborhood-node" onClick={onSelect} key={`${name}-${detail}`}>
      <code>{name}</code>
      <small>{detail}</small>
    </button>
  )

  return (
    <div className="db-neighborhood" aria-label={`Relationships around ${table.name}`}>
      <div className="db-neighborhood-side">
        <span className="db-neighborhood-label">Depends on</span>
        {parents.length ? parents.map((relationship) => relationNode(
          relationship.to,
          `${relationship.fromColumn} → ${relationship.toColumn}`,
          () => onSelect(relationship.to),
        )) : <span className="db-neighborhood-empty">No parent foreign key</span>}
      </div>

      <div className="db-neighborhood-center">
        <span>Selected table</span>
        <code>{table.name}</code>
        <small>{table.purpose}</small>
      </div>

      <div className="db-neighborhood-side">
        <span className="db-neighborhood-label">Referenced by</span>
        {children.length ? children.map((relationship) => relationNode(
          relationship.from,
          `${relationship.onDelete}${relationship.nullable ? ' · optional link' : ''}`,
          () => onSelect(relationship.from),
        )) : <span className="db-neighborhood-empty">No child foreign key</span>}
      </div>
    </div>
  )
}

export function DatabaseMapPage() {
  const [selectedName, setSelectedName] = useState('tasks')
  const [journeyId, setJourneyId] = useState<(typeof runtimeJourneys)[number]['id']>('crud')
  const selected = tables.find((table) => table.name === selectedName) ?? tables[0]
  const journey = runtimeJourneys.find((item) => item.id === journeyId) ?? runtimeJourneys[0]

  return (
    <div className="page database-map-page">
      <div className="database-map-heading">
        <div>
          <p className="eyebrow">Read-only architecture reference</p>
          <h1>Database map</h1>
          <p>Explore the current PostgreSQL contract, its application paths, and the relationships that connect it.</p>
        </div>
        <span className="database-map-count">{tables.length} tables</span>
      </div>

      <section className="content-card db-runtime" aria-labelledby="runtime-flow-title">
        <div className="db-section-heading">
          <div><h2 id="runtime-flow-title">Follow one request</h2><p>Choose a journey to see which backend boundary owns each step.</p></div>
          <Icon name="database" size={22} />
        </div>
        <div className="db-journey-tabs" role="group" aria-label="Backend request journeys">
          {runtimeJourneys.map((item) => <button type="button" aria-pressed={journey.id === item.id} key={item.id} onClick={() => setJourneyId(item.id)}>{item.label}</button>)}
        </div>
        <div className="db-flow" aria-label={`${journey.label} backend flow`}>
          {journey.steps.map(([title, detail], index) => <div className="db-flow-fragment" key={title}>
            {index > 0 && <b aria-hidden="true">→</b>}
            <div className={index === journey.steps.length - 1 ? 'db-flow-primary' : ''}><span>{title}</span><small>{detail}</small></div>
          </div>)}
        </div>
        <p className="db-flow-note">{journey.summary}</p>
      </section>

      <section className="content-card" aria-labelledby="schema-map-title">
        <div className="db-section-heading">
          <div><h2 id="schema-map-title">Schema explorer</h2><p>The selected table, its columns, indexes, and foreign-key context update together.</p></div>
          <div className="db-legend"><ColumnFlag flag="PK" /><ColumnFlag flag="UQ" /><ColumnFlag flag="IDX" /><ColumnFlag flag="NULL" /></div>
        </div>
        <div className="db-schema-explorer-layout">
          <div className="db-schema-workspace">
            <RelationshipNeighborhood table={selected} onSelect={setSelectedName} />
            <div className="db-map-grid">
              {diagramGroups.map((group) => {
                const groupTables = tables.filter((table) => table.group === group)
                return groupTables.length ? <section key={group} className="db-map-group">
                  <h3>{group}</h3>
                  {groupTables.map((table) => {
                    const linked = relationships.some((relationship) => relationship.from === table.name || relationship.to === table.name)
                    return <button id={`db-table-${table.name}`} key={table.name} type="button" className={`db-table-node ${selected.name === table.name ? 'selected' : ''}`} onClick={() => setSelectedName(table.name)} aria-pressed={selected.name === table.name}>
                      <span>{table.name}</span><small>{table.columns.length} columns {linked ? '· linked' : '· standalone'}</small>
                    </button>
                  })}
                </section> : null
              })}
            </div>
            <TableDetail table={selected} />
          </div>
        </div>
      </section>

      <section className="content-card db-platform-features">
        <div><h2>Platform features</h2><p><strong>Extension:</strong> {schemaFeatures.extension}. <strong>Vector:</strong> {schemaFeatures.vectorIndex}.</p></div>
        <div><h3>Backups</h3><p>{schemaFeatures.backups}</p></div>
        <div><h3>Triggers</h3><ul>{schemaFeatures.triggers.map((trigger) => <li key={trigger}>{trigger}</li>)}</ul></div>
        <div><h3>Migration history</h3><ul>{schemaFeatures.migrations.map((migration) => <li key={migration}>{migration}</li>)}</ul></div>
      </section>
    </div>
  )
}
