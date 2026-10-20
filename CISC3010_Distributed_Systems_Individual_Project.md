<!-- Source: https://docs.google.com/document/d/14U_MZDYpDBWg4QQslEfQcDaF4Exe8Ubd-SM6lfRb8wI/edit -->
<!-- Retrieved: 2026-10-12 -->

CISC3010 Distributed Computer Systems

Choose one project and develop a working demo that explains a distributed-system mechanism through code and experiments. This is an individual assignment. AI coding tools are permitted, and you are responsible for understanding and validating your submitted work.

If you have any questions about the project, please feel free to add a comment to this Google Doc.

# Schedule and topic selection

| Milestone | Timing | Exact deadline |
| --- | --- | --- |
| Project release | Start of project | Oct 8 |
| Topic preferences and proposal | Within 7 days of release | Oct 15 |
| Presentation and working demo | 2 weeks after release | Oct 22 |
| Final code and report | 4 weeks after release | Nov 5 |

Submission: Github repo

Hardware: If you need computing resources and AI coding tools, please email TA, Renjie, at [yc68109@connect.um.edu.mo](mailto:yc68109@connect.um.edu.mo).

# Minimum expectations

·       Run interacting components as separate processes or containers, or as explicit peers in a documented simulator. Identify the messages or communication operations between them.

·       Provide an architecture diagram, a working demo, a correctness check, and the experiment described for your selected topic.

·       Make important behavior observable through logs, traces, metrics, or a simple display. A graphical interface is optional.

·       Compare configurations using the same workload and resource limits. Repeat performance measurements and report variation, workload size, and environment.

·       Use your selected paper to explain one design idea, where it appears in your project, and which assumptions you simplify.

# Deliverables and Assessment

## Presentation after two weeks

Presentations will take place on 22, 26, and 29 October 2026. Each student has 20 minutes to present the project, followed by 5 minutes for questions. The presentation order below was assigned randomly.

Session length: Three consecutive 25-minute slots per day, totaling 75 minutes.

| Date | Slot | Student | Student ID |
| --- | --- | --- | --- |
| 22 October Thursday | 1 | SOU CHAK TONG (Paco) | U-C3-2652-3 |
| 22 October Thursday | 2 | TAN SHENGXI | U-C6-2752-0 |
| 22 October Thursday | 3 | LAM IOK HOI (Stephen) | U-C3-2683-4 |
| 26 October Monday | 1 | PEDRO CASTELO DE SOUZA NEMETZ | U-C5-9439-5 |
| 26 October Monday | 2 | SONG XINYUE | U-C6-2746-5 |
| 26 October Monday | 3 | CHEONG KIN NGAI (Bankey) | U-C3-2544-8 |
| 29 October Thursday | 1 | GUO YILIANG | U-C6-2753-1 |
| 29 October Thursday | 2 | NADEZHDA OSIPOVA | U-C6-2732-3 |
| 29 October Thursday | 3 | Reserved for makeup or an additional student | — |

## Slot durations

| Slot | Presentation | Questions |
| --- | --- | --- |
| 1 | Minutes 0 to 20 | Minutes 20 to 25 |
| 2 | Minutes 25 to 45 | Minutes 45 to 50 |
| 3 | Minutes 50 to 70 | Minutes 70 to 75 |

Times above are measured from the start of each day’s session. The final slot on 29 October is reserved for a makeup presentation or an additional student.

## Final submission after five weeks

·       Source code with a README covering setup, dependencies, component startup, the demo, and experiment commands. Identify required hardware and provide small sample inputs.

·       Configuration files, workload generators, correctness checks, raw experiment results, and scripts used to produce your figures or tables.

·       A 3 to 4 page report covering the question, architecture, implementation, correctness evidence, experiments, interpretation, and limitations. References may occupy an additional page.

·       In the report, explain what you changed after presentation feedback and identify your own additions to existing libraries, starter code, or examples.

## Use of AI and existing code

You may use AI for implementation, debugging, tests, documentation, and explanations. Verify generated code and factual claims yourself. Include a brief AI-use statement naming the tools, describing substantial assistance, and explaining how you checked the results. A complete prompt history is not required.

Cite libraries, tutorials, starter code, and existing solutions used in your work. Identify what you implemented or changed. Discussions about concepts are welcome; each student must submit and explain their own project and experiments. Report actual observations, including failed experiments or slowdowns.

## Assessment criteria

| Criterion | Weight |
| --- | --- |
| Working system and correctness evidence | 30% |
| Experimental design and interpretation | 25% |
| Presentation and individual understanding | 25% |
| Reproducibility and documentation | 10% |
| Report quality and connection to the reading | 10% |

All topics are eligible for full marks when their stated minimum scope is completed well. Optional extensions are useful only after the core works. A carefully explained slowdown can be a valid result. AI-use disclosure forms part of documentation.

## Local execution and resources

Multiple processes on one laptop are sufficient. Document shared resources and the limits of local scaling experiments. GPUs and paid cloud services are optional; a small CPU model or the permitted simulation is sufficient for LLM projects. Resolve environment problems early.

# Project Options

Select one of the following fifteen projects. Difficulty is a planning guide for a three-week individual assignment; it does not determine the maximum mark. Build options focus on a small implementation. Use options focus on an application, instrumentation, and experiments around an existing system.

| No | Topic | Approach | Difficulty |
| --- | --- | --- | --- |
| 1 | Fault Tolerant MapReduce | Build | Moderate |
| 2 | Reliable RPC and Duplicate Suppression | Build | Accessible |
| 3 | Raft Leader Election | Build | Moderate |
| 4 | Replicated Key Value Store Using Raft | Use and extend | Moderate with a library |
| 5 | Sharded Key Value Store | Build | Moderate |
| 6 | Mini Distributed File System | Build | Moderate |
| 7 | Dynamo Inspired Replicated Store | Build | Challenging |
| 8 | Spark Caching and Distributed Execution | Use and investigate | Accessible |
| 9 | Kafka Partitioned Logs and Consumer Recovery | Use and investigate | Moderate |
| 10 | Flink Event Time Stream Processing | Use and investigate | Moderate |
| 11 | Kubernetes Self Healing and Rolling Updates | Use and investigate | Moderate |
| 12 | YARN Resource Allocation Between Jobs | Use and investigate | Moderate with a working environment |
| 13 | ZooKeeper Application Leader Coordination | Use and investigate | Moderate |
| 14 | Distributed LLM Serving and Load Balancing | Build around workers | Moderate |
| 15 | Distributed Training and Gradient Synchronization | Use and investigate | Moderate |

## How to use the readings

Read the abstract, architecture, and the sections relevant to your mechanism. You do not need to reproduce an entire paper or its reported performance. Explain one idea accurately and relate it to your code or experiment. For deployed frameworks, consult current official documentation because modern implementations may differ from their original papers.

## Project 1 Fault Tolerant MapReduce

Approach and difficulty: Build | Moderate

MapReduce divides a batch computation into tasks that run across workers. Build a small system to explore how a coordinator distributes work and recovers when a worker stops.

### Minimum implementation

·       Run one coordinator and at least two worker processes communicating through RPC or another explicit messaging interface.

·       Implement map, partitioning of intermediate keys, and reduce for word count or an inverted index. Shared local files are acceptable.

·       Track task assignments and completion; reassign tasks after a timeout and publish completed output safely.

Required experiment: Compare one, two, and four workers on the same input. Kill a worker during a task, show reassignment in the logs, and verify that the final output matches a sequential reference implementation.

Optional extension: Investigate an intentionally slow worker or compare partitioning strategies under skewed input.

Main reading: [MapReduce: Simplified Data Processing on Large Clusters](https://www.usenix.org/conference/osdi-04/mapreduce-simplified-data-processing-large-clusters) (OSDI 2004).

Read the execution overview and worker-failure handling.

[MIT 6.5840 Lab 1 MapReduce](https://pdos.csail.mit.edu/6.824/labs/lab-mr.html)

## Project 2 Reliable RPC and Duplicate Suppression

Approach and difficulty: Build | Accessible

A client may time out even when the server has already executed its request. Build a service that makes this uncertainty visible and handles retries without applying the same update twice.

### Minimum implementation

·       Implement an RPC key-value service with Get and a non-idempotent update such as Append or Increment.

·       Give requests unique identifiers; implement client retries and a server-side record of completed requests and replies.

·       Add a controllable fault injector that drops selected requests or replies. Assume the server remains running.

Required experiment: Drop a reply after the update has executed. Compare behavior with duplicate suppression disabled and enabled, and verify the final value. State why your guarantee depends on the server retaining its request history.

Optional extension: Persist duplicate-suppression metadata and investigate one server restart.

Main reading: [Implementing Remote Procedure Calls](https://www.microsoft.com/en-us/research/publication/implementing-remote-procedure-calls/) (ACM TOCS 1984).

Read about call identifiers, retransmission, and failure semantics.

[MIT 6.5840 Lab 2 Key Value Server as related inspiration](https://pdos.csail.mit.edu/6.824/labs/lab-kvsrv1.html)

## Project 3 Raft Leader Election

Approach and difficulty: Build | Moderate

Raft uses terms, majority voting, and randomized timeouts to elect a leader. Implement the election mechanism and show how peers respond when the leader becomes unavailable.

### Minimum implementation

·       Run three or five peers that exchange vote requests and heartbeats through explicit messages.

·       Implement follower, candidate, and leader states, election terms, voting rules, and randomized election timeouts.

·       Display a timeline of peer states, terms, votes, and leadership changes. Log replication is outside the minimum scope.

Required experiment: Terminate the leader and measure time to a new election when a majority can communicate. Repeat with different timeout ranges and compare election delay and unnecessary leadership changes.

Optional extension: Inject message loss or a network partition; explain why peers can disagree about leadership across different terms.

Main reading: [In Search of an Understandable Consensus Algorithm](https://www.usenix.org/conference/atc14/technical-sessions/presentation/ongaro) (USENIX ATC 2014).

Read Section 5.2 and the election-related rules in Figure 2.

[MIT 6.5840 Lab 3 Part 3A](https://pdos.csail.mit.edu/6.824/labs/lab-raft1.html)

## Project 4 Replicated Key Value Store Using Raft

Approach and difficulty: Use and extend | Moderate with a library

A replicated service keeps data available when one server fails. Use an existing Raft implementation to build a small key-value service and investigate the relationship between replication, commitment, and client acknowledgements.

### Minimum implementation

·       Run a three-replica service using an existing Raft library or clearly identified starter implementation.

·       Implement Put and Get, and expose committed commands and applied state. Document whether reads use the leader, the log, or another mechanism.

·       Implement client reconnection or redirection and show how each replica applies committed updates.

Required experiment: Fail the leader during a sequence of uniquely identified writes. Check acknowledged writes after recovery and record uncertain operations separately. Remove a majority and show whether new writes can complete.

Optional extension: Compare read approaches or investigate snapshotting with a longer update history.

Main reading: [In Search of an Understandable Consensus Algorithm](https://www.usenix.org/conference/atc14/technical-sessions/presentation/ongaro) (USENIX ATC 2014).

Read log replication, commitment, and state-machine safety.

[MIT 6.5840 Lab 4 Fault Tolerant Key Value Service](https://pdos.csail.mit.edu/6.824/labs/lab-kvraft1.html)

## Project 5 Sharded Key Value Store

Approach and difficulty: Build | Moderate

Sharding distributes different keys across storage servers. Build a router and independent storage processes to explore key placement, load balance, and the cost of changing cluster membership.

### Minimum implementation

·       Run a client or router and at least three storage processes supporting Put and Get.

·       Implement both modulo hashing and consistent hashing; display the owner of each key and the number of keys per node.

·       Support adding one node and transferring reassigned keys. Pause writes during migration and document this assumption.

Required experiment: Use the same key set to compare placement balance and the fraction of keys reassigned when a node is added. Verify every value after migration. Include a workload with a frequently accessed key to distinguish key balance from request balance.

Optional extension: Add virtual nodes or investigate replication as a separate mechanism.

Main reading: [Dynamo: Amazon’s Highly Available Key-value Store](https://www.amazon.science/publications/dynamo-amazons-highly-available-key-value-store) (SOSP 2007).

Read the partitioning mechanism; full Dynamo replication is outside this project.

[MIT 6.5840 Lab 5 Sharded Key Value Service as an advanced reference](https://pdos.csail.mit.edu/6.824/labs/lab-shard1.html)

## Project 6 Mini Distributed File System

Approach and difficulty: Build | Moderate

Distributed file systems separate file metadata from data stored across servers. Build a small service for immutable files to explore chunk placement, replication, and retrieval after a storage failure.

### Minimum implementation

·       Run one metadata server and three storage processes with separate storage directories.

·       Split an uploaded file into chunks, record chunk locations, and store at least two copies of each chunk.

·       Implement upload and download with checksums; allow a client to retry another replica when a storage process is unavailable.

Required experiment: Upload a file, stop one storage process, and download the file using remaining replicas. Verify its checksum and compare retrieval latency before and after the failure. State that the metadata server is a single point of failure.

Optional extension: Detect under-replicated chunks and create replacement copies automatically.

Main reading: [The Google File System](https://research.google/pubs/the-google-file-system/) (SOSP 2003).

Read the architecture and replication design. Concurrent mutable writes and GFS append semantics are outside the minimum scope.

## Project 7 Dynamo Inspired Replicated Store

Approach and difficulty: Build | Challenging

Replicas can temporarily disagree when updates are delayed. Build a small replicated store that exposes versions and acknowledgement policies, then examine the tradeoff between availability and observed consistency.

### Minimum implementation

·       Run three replicas with configurable read and write acknowledgement counts, R and W.

·       Expose stored versions and add controllable replication delay. Use one documented rule to resolve conflicting versions.

·       Implement a simple repair mechanism so replicas can converge after delayed communication resumes. Use a fixed replica set.

Required experiment: Compare two R and W configurations on the same operation sequence. Demonstrate a stale read with delayed replication and convergence after repair. Repeat with one unavailable replica; discuss the assumptions behind your observations.

Optional extension: Add read repair or an explicit conflict display for concurrent updates.

Main reading: [Dynamo: Amazon’s Highly Available Key-value Store](https://www.amazon.science/publications/dynamo-amazons-highly-available-key-value-store) (SOSP 2007).

Read replication, versioning, and consistency tradeoffs. Explain why quorum overlap alone does not establish linearizability.

## Project 8 Spark Caching and Distributed Execution

Approach and difficulty: Use and investigate | Accessible

Spark partitions computations across workers and can reuse intermediate data in memory. Develop an iterative application and investigate when caching improves its execution time.

### Minimum implementation

·       Run a Spark driver and at least two worker processes or executors in a documented local deployment.

·       Implement an iterative workload such as PageRank, repeated aggregation, or repeated queries over a shared dataset.

·       Create comparable runs with caching enabled and disabled; show partitions, stages, and cache behavior through logs or the Spark interface.

Required experiment: Compare caching enabled and disabled for several iterations and dataset sizes. Separate initial materialization from subsequent iterations, repeat measurements, and explain any slowdown or lack of improvement.

Optional extension: Terminate an executor and investigate recovery or examine the effect of skewed partitions.

Main reading: [Resilient Distributed Datasets: A Fault-Tolerant Abstraction for In-Memory Cluster Computing](https://www.usenix.org/conference/nsdi12/technical-sessions/presentation/zaharia) (NSDI 2012).

Read RDDs, persistence, and lineage-based recovery.

[Apache Spark RDD Programming Guide](https://spark.apache.org/docs/latest/rdd-programming-guide)

## Project 9 Kafka Partitioned Logs and Consumer Recovery

Approach and difficulty: Use and investigate | Moderate

Kafka stores events in partitioned logs, while consumers track their progress using offsets. Develop a producer and consumers to examine parallel consumption, replay, and recovery.

### Minimum implementation

·       Create a topic with multiple partitions and run at least two consumers in one group.

·       Produce events with unique IDs and record partition, offset, consumer identity, and processed output.

·       Make offset commits explicit and build a checker that detects missing or repeatedly processed event IDs. A single broker is acceptable for the core consumer experiment.

Required experiment: Restart a consumer during processing and observe partition reassignment and replay. Vary consumer count while holding partition count fixed. Explain how commit timing affects duplicates and missing application effects.

Optional extension: Deploy multiple brokers with replication and investigate broker failure.

Main reading: [Kafka: a Distributed Messaging System for Log Processing](https://www.microsoft.com/en-us/research/wp-content/uploads/2017/09/Kafka.pdf) (NetDB 2011).

Read partitions, consumer groups, and offsets. Use current documentation for current client behavior.

[Apache Kafka documentation](https://kafka.apache.org/)

## Project 10 Flink Event Time Stream Processing

Approach and difficulty: Use and investigate | Moderate

Streaming applications must decide how to handle events that arrive late or out of order. Build a windowed aggregation and compare results based on arrival time and event timestamps.

### Minimum implementation

·       Generate events with an ID, event timestamp, and value, with controllable delay and arrival order.

·       Implement equivalent processing-time and event-time windowed counts or sums, using watermarks for event time.

·       Run multiple processing tasks and report the window outputs, late-event policy, and watermark configuration.

Required experiment: Replay a known event sequence with out-of-order arrivals. Compare window assignments and aggregates against an offline reference based on event time. Vary watermark delay and measure the tradeoff between result latency and completeness.

Optional extension: Add checkpoint recovery and verify restored state with a replayable source.

Main reading: [Apache Flink: Stream and Batch Processing in a Single Engine](https://sites.computer.org/debull/A15dec/p28.pdf) (IEEE Data Engineering Bulletin 2015).

Read the dataflow architecture and supplement it with current event-time and watermark documentation.

[Apache Flink documentation](https://nightlies.apache.org/flink/flink-docs-stable/)

## Project 11 Kubernetes Self Healing and Rolling Updates

Approach and difficulty: Use and investigate | Moderate

Kubernetes controllers continuously reconcile deployed workloads with their desired state. Deploy a replicated web service and observe how this mechanism supports replacement of failed Pods and application updates.

### Minimum implementation

·       Use a local Kubernetes cluster, such as kind or minikube, to deploy a small HTTP application with at least two replicas.

·       Configure a Service and readiness checks. Make each response identify the application version and serving Pod.

·       Run a continuous request generator and collect Pod events, replica counts, response latency, and failed requests.

Required experiment: Delete a Pod and then perform a rolling update. Measure time until a replacement is ready and record request failures. Compare two rollout configurations; explain desired state, observed state, and readiness.

Optional extension: Add horizontal Pod autoscaling and investigate its response to a changing workload.

Main reading: [Large-scale Cluster Management at Google with Borg](https://research.google/pubs/large-scale-cluster-management-at-google-with-borg/) (EuroSys 2015).

Use Borg as background on cluster management; Kubernetes behavior should be grounded in its own documentation.

[Kubernetes Self Healing](https://kubernetes.io/docs/concepts/architecture/self-healing/)

## Project 12 YARN Resource Allocation Between Jobs

Approach and difficulty: Use and investigate | Moderate with a working environment

YARN separates cluster resource allocation from application execution. Deploy competing batch jobs and investigate how scheduler queues divide a limited resource pool.

### Minimum implementation

·       Run a ResourceManager and one or more NodeManagers in a local deployment. Identify each application’s ApplicationMaster and allocated containers.

·       Submit two repeatable batch jobs to separate CapacityScheduler queues and record their resource requests and allocations.

·       Configure two queue-capacity settings and collect waiting time, allocated resources, and completion time.

Required experiment: Run both jobs concurrently under each configuration with the same total resources and inputs. Make minimum and maximum queue capacities explicit. Explain whether idle capacity can be borrowed and how that changes each job’s completion time.

Optional extension: Investigate the effect of one failed NodeManager or compare application priorities.

Main reading: [Apache Hadoop YARN: Yet Another Resource Negotiator](https://www.cs.cmu.edu/~garth/15719/papers/yarn.pdf) (SoCC 2013).

Read the resource-management architecture and scheduling responsibilities.

## Project 13 ZooKeeper Application Leader Coordination

Approach and difficulty: Use and investigate | Moderate

Applications can use a coordination service to select one active leader. Build several competing application processes that use ZooKeeper to track membership and choose which process should perform a shared task.

### Minimum implementation

·       Run a three-server ZooKeeper ensemble and at least three application contenders.

·       Use ephemeral sequential nodes and watches to choose an application leader; display session IDs, contenders, and leadership changes.

·       Have the selected leader perform a visible periodic task. Handle session loss by stopping leader activity and document the failure assumptions.

Required experiment: Terminate the application leader and measure replacement after session expiry. Compare two session-timeout settings. Distinguish the application leader from ZooKeeper’s internal leader and explain the limits of your external-task exclusivity guarantee.

Optional extension: Add fencing tokens enforced by the task destination to reject work from an obsolete leader.

Main reading: [ZooKeeper: Wait-free Coordination for Internet-scale Systems](https://www.usenix.org/conference/usenix-atc-10/zookeeper-wait-free-coordination-internet-scale-systems) (USENIX ATC 2010).

Read the coordination interface and client primitives, then consult the leader-election recipe.

[ZooKeeper Recipes and Solutions](https://zookeeper.apache.org/doc/r3.4.14/recipes.html)

## Project 14 Distributed LLM Serving and Load Balancing

Approach and difficulty: Build around workers | Moderate

An inference service routes concurrent requests to workers whose queues and execution times may differ. Build a small serving system and investigate how routing policies affect throughput and response time.

### Minimum implementation

·       Run a request router and at least two separate inference worker processes with visible request queues.

·       Use a small CPU model or a clearly labeled generation simulator with explicit per-token timing assumptions; support incremental responses.

·       Implement round-robin and least-outstanding-request routing. Log arrival, assignment, first response, completion, and output length.

Required experiment: Replay the same mixture of short and long requests under both policies. Measure throughput, time to first token, and p95 completion latency. State the arrival-rate model, hardware limits, and whether the router or workers are saturated.

Optional extension: Compare static and continuous batching, or investigate recovery after a worker stops.

Main reading: [Orca: A Distributed Serving System for Transformer-Based Generative Models](https://www.usenix.org/conference/osdi22/presentation/yu) (OSDI 2022).

Read Orca’s serving architecture and scheduling. Explain how its iteration-level scheduling differs from your routing experiment.

## Project 15 Distributed Training and Gradient Synchronization

Approach and difficulty: Use and investigate | Moderate

Data-parallel training gives each worker a model replica and different examples, then synchronizes gradients before updates. Build a small training demo to examine consistency between replicas and the cost of communication.

### Minimum implementation

·       Use two processes to train a tiny Transformer or small classifier on separate data partitions. CPU execution with Gloo is sufficient.

·       Implement synchronized training using PyTorch DistributedDataParallel or explicit gradient averaging, and an unsynchronized comparison.

·       Log loss, iteration time, and a numerical comparison of model parameters across replicas. State local and total batch sizes.

Required experiment: Compare replica agreement with synchronization enabled and disabled. For a one-process baseline, match total batch size and update count. Measure communication overhead using documented instrumentation or a simple explicit synchronization path, and explain your timing method.

Optional extension: Vary batch size or investigate gradient accumulation and synchronization frequency.

Main reading: [PyTorch Distributed: Experiences on Accelerating Data Parallel Training](https://arxiv.org/abs/2006.15704) (VLDB 2020).

Read model replication, gradient synchronization, and the interaction between computation and communication.

[PyTorch Distributed Data Parallel Tutorial](https://docs.pytorch.org/tutorials/intermediate/ddp_tutorial.html)

[PyTorch distributed communication documentation](https://docs.pytorch.org/docs/stable/distributed.html)

## Final Submission Checklist

·       The README commands start the demo in the documented environment.

·       The architecture diagram matches the submitted code and configuration.

·       Correctness checks and experiment scripts run on the provided sample data.

·       Figures can be traced to the submitted raw results.

·       The report explains assumptions, limitations, and changes made after feedback.

·       External code, references, and substantial AI assistance are disclosed.


