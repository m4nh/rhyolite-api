# Rhyolite API

This is the API module of the Rhyolite framework. The API provides an interface to a PostgreSQL database and a lightweight file storage system. The rhyolite framework is a graph-based data wharehouse with based reconfigurable data models.

<details>
<summary><strong>Datamodel</strong></summary>

## Datamodel

The Datamodel of Rhyolite is based on the following core entities:

- **Node**: Represents a unit of data or a resource in the system. Nodes have these fields:
  - `id`: A unique identifier for the node (PRIMARY KEY).
  - `kind`: The kind or type of the node (e.g., "document", "thing", "event").
  - `created_at`: Timestamp of when the node was created.
  - `updated_at`: Timestamp of the last update to the node.
  - `payload`: A JSONB field that can store arbitrary data associated with the node.
- **Edge**: Represents a directed relationship between two nodes:
  - `from`: The ID of the source node (FOREIGN KEY referencing Node.id).
  - `to`: The ID of the target node (FOREIGN KEY referencing Node.id).
  - `relation`: A string that describes the type of relationship (e.g., "parent", "related_to").
  - `created_at`: Timestamp of when the edge was created.
- **Kind**: Represents the schema of a node-kind payload:
  - `name`: The name of the kind (PRIMARY KEY).
  - `schema`: A JSONB field that defines the JSON schema for the payload of nodes of this kind.
- **EdgesKind**: Represents the allowed relationships between kinds:
  - `from_kind`: The name of the source kind (FOREIGN KEY referencing Kind.name).
  - `to_kind`: The name of the target kind (FOREIGN KEY referencing Kind.name).
  - `relation`: A string that describes the type of relationship allowed between these kinds.
- **Attachment**: Represents a file attachment associated with a node:
  - `id`: A unique identifier for the attachment (PRIMARY KEY).
  - `node_id`: The ID of the node to which the attachment is linked (FOREIGN KEY referencing Node.id).
  - `mime_type`: The MIME type of the attachment (e.g., "image/png", "application/pdf").
  - `name`: A display name for the attachment (optional when uploading; defaults to the uploaded file's filename).
  - `file_path`: The file system path where the attachment is stored.
  - `created_at`: Timestamp of when the attachment was created.
</details>

<details>
<summary><strong>API</strong></summary>

## API


The API provides endpoints to create, read, update, and delete these entities, as well as to manage relationships and attachments. It also includes validation mechanisms to ensure that nodes conform to their defined kinds and that edges respect the allowed relationships between kinds.

### Endpoints

- `POST /kind`: Create a new kind with a specified JSON schema.
- `GET /kind/{name}`: Retrieve the schema for a specified kind.
- `GET /kinds`: List all defined kinds.
- `DELETE /kind/{name}`: Delete a specified kind.
- `POST /edges-kind`: Define allowed relationships between kinds.
- `GET /edges-kinds/{from_kind}/{to_kind}`: Retrieve allowed relationships between two specified kinds.
- `GET /edges-kinds/{from_kind}`: Retrieve all allowed relationships from a specified kind.
- `GET /edges-kinds/{from_kind}/{to_kind}/{relation}`: Retrieve a specific allowed relationship between two kinds.
- `GET /edges-kinds`: List all defined edges kinds.
- `DELETE /edges-kind/{from_kind}/{to_kind}/{relation}`: Delete a specified edges kind.
- `POST /node`: Create a new node of a specified kind with a payload.
- `POST /nodes/search`: Search nodes by dot-notated payload fields. Body: `{ "kinds": ["kindA","kindB"], "query": {"field.sub": "*value*", "count": 3} , "limit": 100 }` (omit `kinds` or use `null` to search all kinds).
- `GET /node/{id}`: Retrieve a node by its ID.
- `PUT /node/{id}`: Update a node's payload.
- `DELETE /node/{id}`: Delete a node by its ID.
- `POST /edge`: Create a new edge between two nodes.
- `GET /outgoing-edges/{node_id}`: Retrieve all outgoing edges from a specified node.
- `GET /incoming-edges/{node_id}`: Retrieve all incoming edges to a specified node.
- `GET /edges/{from_id}/{to_id}`: Retrieve edges between two specified nodes.
- `DELETE /edge/{from_id}/{to_id}/{relation}`: Delete a specified edge.
- `POST /attachment`: Upload a new attachment to a specified node. Optionally provide `?name=<display-name>` as a query parameter to set the attachment name; otherwise the uploaded file's filename is used.
- `GET /attachment/{id}`: Retrieve an attachment by its ID.
- `GET /attachments/{node_id}`: List all attachments for a specified node.
- `DELETE /attachment/{id}`: Delete an attachment by its ID.
- `GET /schema`: Retrieve the whole list of Kinds and EdgesKinds as a JSON object.
- `POST /schema`: Push a full schema definition (Kinds and EdgesKinds) to the server not replacing existing definitions if they already exist.
- `POST /reset`: Reset the database by deleting all nodes, edges, kinds, edges kinds, and attachments.


#### Endpoint special notes

* When creating a node, the API validates the payload against the JSON schema defined for the specified kind. If the payload does not conform to the schema, the API returns a 400 Bad Request error with details about the validation errors.
* `POST /nodes/search` - Search notes by payload fields with a JSON body like `{ "kinds": ["kindA"], "query": {"name": "*alpha*", "metadata.one": 2}, "limit": 100 }`.
  - Keys support dot notation to access nested fields (e.g. `metadata.one`).
  - String values may use `*` as a wildcard; these are translated to SQL ILIKE patterns (case-insensitive substring match).
  - Numeric and boolean values are matched exactly.
  - If `kinds` is omitted or `null`, all kinds are searched.
* When creating an edge, the API checks that the relationship between the kinds of the source and target nodes is allowed according to the defined edges kinds. If the relationship is not allowed, the API returns a 400 Bad Request error.
* You cannot delete a kind if there are existing nodes of that kind in the database. Attempting to do so will result in a 400 Bad Request error.
* You cannot delete an edges kind if there are existing edges in the database that use that relationship. Attempting to do so will result in a 400 Bad Request error.
* When uploading an attachment, the API stores the file in the file storage system and records the file path in the database. You can provide an optional `name` query parameter when posting an attachment; if omitted, the uploaded file's filename will be used as the attachment name. The API returns the ID of the newly created attachment.
* When a node is deleted, all associated edges and attachments are also deleted to maintain data integrity.

#### Implementation details

The Rhyolite API is implemented using FastAPI, a modern web framework for building APIs with Python 3. The database interactions are handled using SQLAlchemy and Pydantic 2 is used for data validation and serialization. The file storage system is implemented using local file storage, but is implemented behind an abstraction layer to allow for easy replacement with other storage backends in the future.

</details>



## Kubernetes

This repo includes a minimal Kubernetes setup that deploys:

- PostgreSQL (with a PVC)
- a one-shot seed `Job` that runs once and then completes
- the Rhyolite API `Deployment`

Manifests live under [k8s/](k8s/).

### Build images

The Kubernetes manifests expect these images:

- `rhyolite-api:latest` (built from [Dockerfile](Dockerfile))
- `rhyolite-seed:latest` (built from [seed.Dockerfile](seed.Dockerfile))
- `rhyolite-test:latest` (built from [test.Dockerfile](test.Dockerfile))

Build them locally:

- `docker build -t rhyolite-api:latest -f Dockerfile .`
- `docker build -t rhyolite-seed:latest -f seed.Dockerfile .`
- `docker build -t rhyolite-test:latest -f test.Dockerfile .`

If you are using a remote cluster (not Docker Desktop / kind / minikube), push these images to a registry and update the image names in the manifests (or via Kustomize).

### Deploy

- `kubectl apply -k k8s/`

Or (same resources; useful if you want a dedicated overlay folder):

- `kubectl apply -k k8s/testing/`

### Access the API

- `kubectl port-forward svc/rhyolite-api 8000:8000`
- Open `http://localhost:8000/docs`