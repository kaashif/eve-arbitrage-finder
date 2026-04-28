use std::cmp::Ordering;
use std::collections::VecDeque;
use std::fs::{self, File};
use std::io::{BufReader, BufWriter, Read, Write};
use std::path::{Path, PathBuf};

use anyhow::{Context, Result, anyhow, bail};
use bytemuck::{Pod, Zeroable};
use bzip2::read::BzDecoder;
use chrono::{DateTime, NaiveDateTime, Utc};
use clap::{Parser, Subcommand};
use memmap2::Mmap;
use rustc_hash::{FxHashMap, FxHashSet};

const ORDER_MAGIC: &[u8; 16] = b"EVEARB_ORDERS_01";
const ARB_MAGIC: &[u8; 16] = b"EVEARB_ARBS___01";
const HEADER_BYTES: usize = 32;
const NO_SNAPSHOT_TS: i64 = i64::MIN;

#[derive(Parser)]
#[command(author, version, about)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    Export {
        #[arg(long, default_value = "data.everef.net/market-orders/history/2023/2023-01-01/market-orders-2023-01-01_*.v3.csv.bz2")]
        market_glob: String,
        #[arg(long, default_value = "mapSolarSystemJumps.csv")]
        jumps_file: PathBuf,
        #[arg(long, default_value = ".cache/eve-arb")]
        cache_dir: PathBuf,
        #[arg(long, default_value_t = 1_000_000_000.0)]
        wallet: f64,
        #[arg(long, default_value_t = 45)]
        seconds_per_jump: i64,
        #[arg(long, default_value_t = 25)]
        per_type_candidate_limit: usize,
        #[arg(long)]
        max_snapshots: Option<usize>,
        #[arg(long, default_value = "day_arbitrages_all.bin")]
        out: PathBuf,
        #[arg(long)]
        csv_out: Option<PathBuf>,
    },
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Zeroable, Pod)]
struct OrderRecord {
    order_id: u64,
    price: f64,
    volume_remain: u32,
    min_volume: u32,
    system_id: u32,
    type_id: u32,
    is_buy_order: u8,
    _pad: [u8; 7],
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Zeroable, Pod)]
struct ArbitrageRecord {
    snapshot_ts: i64,
    arrival_ts: i64,
    arrival_snapshot_ts: i64,
    sell_order_id: u64,
    buy_order_id: u64,
    type_id: u32,
    from_system: u32,
    to_system: u32,
    gate_jumps: u16,
    can_take_advantage: u8,
    _pad0: u8,
    quantity: u32,
    route_seconds: u32,
    sell_price: f64,
    buy_price: f64,
    investment: f64,
    profit: f64,
    isk_per_hour: f64,
    total_return_pct: f64,
    wallet_return_pct: f64,
}

#[derive(Debug)]
struct MappedRecords<T: Pod> {
    _mmap: Mmap,
    records: *const [T],
}

impl<T: Pod> MappedRecords<T> {
    fn records(&self) -> &[T] {
        unsafe { &*self.records }
    }
}

#[derive(Debug)]
struct Snapshot {
    ts: i64,
    orders: MappedRecords<OrderRecord>,
}

#[derive(Default)]
struct TypeBook {
    sells: Vec<OrderRecord>,
    buys: Vec<OrderRecord>,
}

#[derive(Clone, Copy)]
struct BuyOrder {
    price: f64,
    volume_remain: u32,
    min_volume: u32,
}

struct JumpGraph {
    system_to_index: FxHashMap<u32, usize>,
    adjacency: Vec<Vec<usize>>,
}

struct DistanceCache<'a> {
    graph: &'a JumpGraph,
    by_source: FxHashMap<u32, Vec<u16>>,
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    match cli.command {
        Command::Export {
            market_glob,
            jumps_file,
            cache_dir,
            wallet,
            seconds_per_jump,
            per_type_candidate_limit,
            max_snapshots,
            out,
            csv_out,
        } => export(ExportConfig {
            market_glob,
            jumps_file,
            cache_dir,
            wallet,
            seconds_per_jump,
            per_type_candidate_limit,
            max_snapshots,
            out,
            csv_out,
        }),
    }
}

struct ExportConfig {
    market_glob: String,
    jumps_file: PathBuf,
    cache_dir: PathBuf,
    wallet: f64,
    seconds_per_jump: i64,
    per_type_candidate_limit: usize,
    max_snapshots: Option<usize>,
    out: PathBuf,
    csv_out: Option<PathBuf>,
}

fn export(config: ExportConfig) -> Result<()> {
    fs::create_dir_all(&config.cache_dir)?;
    let graph = read_jump_graph(&config.jumps_file)?;
    let snapshots = load_snapshots(&config.market_glob, &config.cache_dir, config.max_snapshots)?;
    if snapshots.is_empty() {
        bail!("no market snapshots matched {}", config.market_glob);
    }

    let buy_maps = snapshots
        .iter()
        .map(|snapshot| build_buy_map(snapshot.orders.records()))
        .collect::<Vec<_>>();

    let mut distance_cache = DistanceCache::new(&graph);
    let mut output = Vec::new();

    for (snapshot_index, snapshot) in snapshots.iter().enumerate() {
        eprintln!(
            "analyzing snapshot {}/{} {}",
            snapshot_index + 1,
            snapshots.len(),
            format_ts(snapshot.ts)
        );
        let mut rows = analyze_snapshot(
            snapshot,
            snapshot_index,
            &snapshots,
            &buy_maps,
            &mut distance_cache,
            config.wallet,
            config.seconds_per_jump,
            config.per_type_candidate_limit,
        )?;
        output.append(&mut rows);
    }

    output.sort_unstable_by(|a, b| {
        a.snapshot_ts
            .cmp(&b.snapshot_ts)
            .then_with(|| b.can_take_advantage.cmp(&a.can_take_advantage))
            .then_with(|| cmp_f64_desc(a.total_return_pct, b.total_return_pct))
            .then_with(|| cmp_f64_desc(a.profit, b.profit))
    });

    write_records(&config.out, ARB_MAGIC, &output)?;
    eprintln!("wrote {} binary arbitrage rows to {}", output.len(), config.out.display());

    if let Some(csv_path) = config.csv_out {
        write_csv(&csv_path, &output)?;
        eprintln!("wrote CSV compatibility output to {}", csv_path.display());
    }

    Ok(())
}

fn analyze_snapshot(
    snapshot: &Snapshot,
    snapshot_index: usize,
    snapshots: &[Snapshot],
    buy_maps: &[FxHashMap<u64, BuyOrder>],
    distance_cache: &mut DistanceCache<'_>,
    wallet: f64,
    seconds_per_jump: i64,
    candidate_limit: usize,
) -> Result<Vec<ArbitrageRecord>> {
    let orders = snapshot.orders.records();
    let mut type_books: FxHashMap<u32, TypeBook> = FxHashMap::default();
    let mut average_acc: FxHashMap<u32, (u64, f64)> = FxHashMap::default();

    for &order in orders {
        let volume_value = order.volume_remain as f64 * order.price;
        let avg = average_acc.entry(order.type_id).or_insert((0, 0.0));
        avg.0 += order.volume_remain as u64;
        avg.1 += volume_value;

        let book = type_books.entry(order.type_id).or_default();
        if order.is_buy_order != 0 {
            book.buys.push(order);
        } else {
            book.sells.push(order);
        }
    }

    let mut rows = Vec::new();
    for (type_id, mut book) in type_books {
        if book.sells.is_empty() || book.buys.is_empty() {
            continue;
        }

        book.sells.sort_unstable_by(|a, b| cmp_f64_asc(a.price, b.price));
        book.buys.sort_unstable_by(|a, b| cmp_f64_desc(a.price, b.price));

        let min_sell = book.sells[0].price;
        let max_buy = book.buys[0].price;
        if min_sell >= max_buy {
            continue;
        }

        let sell_len = if candidate_limit == 0 {
            book.sells.len()
        } else {
            candidate_limit.min(book.sells.len())
        };
        let buy_len = if candidate_limit == 0 {
            book.buys.len()
        } else {
            candidate_limit.min(book.buys.len())
        };

        for sell in book.sells[..sell_len].iter().copied().filter(|sell| sell.price < max_buy) {
            for buy in book.buys[..buy_len].iter().copied().filter(|buy| buy.price > min_sell) {
                if sell.price >= buy.price || sell.volume_remain <= buy.min_volume {
                    continue;
                }

                let Some(jumps) = distance_cache.distance(sell.system_id, buy.system_id) else {
                    continue;
                };

                let max_quantity = sell.volume_remain.min(buy.volume_remain);
                let affordable_quantity = (wallet / sell.price).floor().max(0.0) as u32;
                let quantity = max_quantity.min(affordable_quantity);
                if quantity == 0 {
                    continue;
                }

                let investment = quantity as f64 * sell.price;
                let profit = quantity as f64 * (buy.price - sell.price);
                let charged_legs = i64::from(jumps.max(1));
                let route_seconds = charged_legs * seconds_per_jump;
                let arrival_ts = snapshot.ts + route_seconds;
                let arrival_snapshot_index = round_up_snapshot(snapshots, snapshot_index, arrival_ts);
                let arrival_snapshot_ts = arrival_snapshot_index
                    .map(|index| snapshots[index].ts)
                    .unwrap_or(NO_SNAPSHOT_TS);

                let can_take_advantage = arrival_snapshot_index
                    .and_then(|index| buy_maps[index].get(&buy.order_id))
                    .is_some_and(|arrival_buy| {
                        arrival_buy.price >= buy.price
                            && arrival_buy.volume_remain >= quantity
                            && quantity >= arrival_buy.min_volume
                            && profit > 0.0
                    });

                rows.push(ArbitrageRecord {
                    snapshot_ts: snapshot.ts,
                    arrival_ts,
                    arrival_snapshot_ts,
                    sell_order_id: sell.order_id,
                    buy_order_id: buy.order_id,
                    type_id,
                    from_system: sell.system_id,
                    to_system: buy.system_id,
                    gate_jumps: jumps,
                    can_take_advantage: u8::from(can_take_advantage),
                    _pad0: 0,
                    quantity,
                    route_seconds: route_seconds as u32,
                    sell_price: sell.price,
                    buy_price: buy.price,
                    investment,
                    profit,
                    isk_per_hour: profit / route_seconds as f64 * 3600.0,
                    total_return_pct: 100.0 * profit / investment,
                    wallet_return_pct: 100.0 * profit / wallet,
                });
            }
        }
    }

    Ok(rows)
}

fn load_snapshots(
    market_glob: &str,
    cache_dir: &Path,
    max_snapshots: Option<usize>,
) -> Result<Vec<Snapshot>> {
    let mut paths = glob::glob(market_glob)?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    paths.sort();

    let mut snapshots = Vec::new();
    if let Some(max) = max_snapshots {
        paths.truncate(max);
    }

    for path in paths {
        let ts = snapshot_ts_from_path(&path)
            .with_context(|| format!("could not parse snapshot time from {}", path.display()))?;
        let cache_path = cache_dir.join(format!(
            "{}.orders.bin",
            path.file_name()
                .and_then(|name| name.to_str())
                .ok_or_else(|| anyhow!("invalid filename {}", path.display()))?
        ));
        if !cache_path.exists() {
            eprintln!("building order cache {}", cache_path.display());
            let orders = read_market_orders(&path)?;
            write_records(&cache_path, ORDER_MAGIC, &orders)?;
        }
        let orders = map_records::<OrderRecord>(&cache_path, ORDER_MAGIC)?;
        snapshots.push(Snapshot {
            ts,
            orders,
        });
    }

    snapshots.sort_by_key(|snapshot| snapshot.ts);
    Ok(snapshots)
}

fn read_market_orders(path: &Path) -> Result<Vec<OrderRecord>> {
    let file = File::open(path)?;
    let reader: Box<dyn Read> = if path.extension().is_some_and(|ext| ext == "bz2") {
        Box::new(BzDecoder::new(BufReader::new(file)))
    } else {
        Box::new(BufReader::new(file))
    };
    let mut csv = csv::Reader::from_reader(reader);
    let headers = csv.headers()?.clone();
    let idx = |name| -> Result<usize> {
        headers
            .iter()
            .position(|header| header == name)
            .ok_or_else(|| anyhow!("missing column {name} in {}", path.display()))
    };
    let is_buy_idx = idx("is_buy_order")?;
    let order_id_idx = idx("order_id")?;
    let price_idx = idx("price")?;
    let volume_remain_idx = idx("volume_remain")?;
    let min_volume_idx = idx("min_volume")?;
    let system_id_idx = idx("system_id")?;
    let type_id_idx = idx("type_id")?;
    let universe_idx = idx("universe_id")?;

    let mut orders = Vec::new();
    for record in csv.records() {
        let record = record?;
        if record.get(universe_idx) != Some("eve") {
            continue;
        }
        orders.push(OrderRecord {
            order_id: parse(record.get(order_id_idx), "order_id")?,
            price: parse(record.get(price_idx), "price")?,
            volume_remain: parse(record.get(volume_remain_idx), "volume_remain")?,
            min_volume: parse(record.get(min_volume_idx), "min_volume")?,
            system_id: parse(record.get(system_id_idx), "system_id")?,
            type_id: parse(record.get(type_id_idx), "type_id")?,
            is_buy_order: u8::from(record.get(is_buy_idx) == Some("true")),
            _pad: [0; 7],
        });
    }
    Ok(orders)
}

fn read_jump_graph(path: &Path) -> Result<JumpGraph> {
    let file = File::open(path)?;
    let reader: Box<dyn Read> = if path.extension().is_some_and(|ext| ext == "bz2") {
        Box::new(BzDecoder::new(BufReader::new(file)))
    } else {
        Box::new(BufReader::new(file))
    };
    let mut csv = csv::Reader::from_reader(reader);
    let headers = csv.headers()?.clone();
    let from_idx = headers
        .iter()
        .position(|header| header == "fromSolarSystemID")
        .ok_or_else(|| anyhow!("missing fromSolarSystemID"))?;
    let to_idx = headers
        .iter()
        .position(|header| header == "toSolarSystemID")
        .ok_or_else(|| anyhow!("missing toSolarSystemID"))?;

    let mut edges = Vec::new();
    let mut systems = FxHashSet::default();
    for record in csv.records() {
        let record = record?;
        let from: u32 = parse(record.get(from_idx), "fromSolarSystemID")?;
        let to: u32 = parse(record.get(to_idx), "toSolarSystemID")?;
        systems.insert(from);
        systems.insert(to);
        edges.push((from, to));
    }

    let mut system_to_index = FxHashMap::default();
    for system_id in systems {
        let index = system_to_index.len();
        system_to_index.insert(system_id, index);
    }

    let mut adjacency = vec![Vec::new(); system_to_index.len()];
    for (from, to) in edges {
        let from_index = system_to_index[&from];
        let to_index = system_to_index[&to];
        adjacency[from_index].push(to_index);
        adjacency[to_index].push(from_index);
    }

    Ok(JumpGraph {
        system_to_index,
        adjacency,
    })
}

impl<'a> DistanceCache<'a> {
    fn new(graph: &'a JumpGraph) -> Self {
        Self {
            graph,
            by_source: FxHashMap::default(),
        }
    }

    fn distance(&mut self, from: u32, to: u32) -> Option<u16> {
        let to_index = *self.graph.system_to_index.get(&to)?;
        if !self.by_source.contains_key(&from) {
            let distances = self.bfs_from(from)?;
            self.by_source.insert(from, distances);
        }
        let distances = self.by_source.get(&from)?;
        let distance = distances[to_index];
        (distance != u16::MAX).then_some(distance)
    }

    fn bfs_from(&self, from: u32) -> Option<Vec<u16>> {
        let start = *self.graph.system_to_index.get(&from)?;
        let mut distances = vec![u16::MAX; self.graph.adjacency.len()];
        let mut queue = VecDeque::new();
        distances[start] = 0;
        queue.push_back(start);

        while let Some(node) = queue.pop_front() {
            let next_distance = distances[node].saturating_add(1);
            for &neighbor in &self.graph.adjacency[node] {
                if distances[neighbor] == u16::MAX {
                    distances[neighbor] = next_distance;
                    queue.push_back(neighbor);
                }
            }
        }

        Some(distances)
    }
}

fn build_buy_map(orders: &[OrderRecord]) -> FxHashMap<u64, BuyOrder> {
    let mut buys = FxHashMap::default();
    for order in orders.iter().copied().filter(|order| order.is_buy_order != 0) {
        buys.insert(
            order.order_id,
            BuyOrder {
                price: order.price,
                volume_remain: order.volume_remain,
                min_volume: order.min_volume,
            },
        );
    }
    buys
}

fn round_up_snapshot(snapshots: &[Snapshot], start_index: usize, arrival_ts: i64) -> Option<usize> {
    snapshots[start_index..]
        .binary_search_by_key(&arrival_ts, |snapshot| snapshot.ts)
        .map(|index| start_index + index)
        .or_else(|index| {
            let absolute = start_index + index;
            (absolute < snapshots.len()).then_some(absolute).ok_or(index)
        })
        .ok()
}

fn write_records<T: Pod>(path: &Path, magic: &[u8; 16], records: &[T]) -> Result<()> {
    if let Some(parent) = path.parent() {
        if !parent.as_os_str().is_empty() {
            fs::create_dir_all(parent)?;
        }
    }
    let mut out = BufWriter::new(File::create(path)?);
    out.write_all(magic)?;
    out.write_all(&(std::mem::size_of::<T>() as u64).to_le_bytes())?;
    out.write_all(&(records.len() as u64).to_le_bytes())?;
    out.write_all(bytemuck::cast_slice(records))?;
    out.flush()?;
    Ok(())
}

fn map_records<T: Pod>(path: &Path, magic: &[u8; 16]) -> Result<MappedRecords<T>> {
    let file = File::open(path)?;
    let mmap = unsafe { Mmap::map(&file)? };
    if mmap.len() < HEADER_BYTES {
        bail!("{} is too short", path.display());
    }
    if &mmap[..16] != magic {
        bail!("{} has unexpected magic", path.display());
    }
    let record_size = u64::from_le_bytes(mmap[16..24].try_into().unwrap()) as usize;
    if record_size != std::mem::size_of::<T>() {
        bail!(
            "{} record size mismatch: got {}, expected {}",
            path.display(),
            record_size,
            std::mem::size_of::<T>()
        );
    }
    let count = u64::from_le_bytes(mmap[24..32].try_into().unwrap()) as usize;
    let bytes = &mmap[HEADER_BYTES..];
    let expected = count
        .checked_mul(record_size)
        .ok_or_else(|| anyhow!("{} record byte length overflow", path.display()))?;
    if bytes.len() != expected {
        bail!("{} has wrong payload length", path.display());
    }
    let records = bytemuck::try_cast_slice::<u8, T>(bytes)
        .map_err(|_| anyhow!("{} payload is not aligned for typed view", path.display()))?;
    let records_ptr = records as *const [T];
    Ok(MappedRecords {
        _mmap: mmap,
        records: records_ptr,
    })
}

fn write_csv(path: &Path, rows: &[ArbitrageRecord]) -> Result<()> {
    let mut writer = csv::Writer::from_path(path)?;
    writer.write_record([
        "snapshot_time",
        "arrival_time",
        "arrival_snapshot_time",
        "type_id",
        "from_system",
        "to_system",
        "gate_jumps",
        "route_seconds",
        "route_minutes",
        "can_take_advantage",
        "executable_quantity",
        "sell_price",
        "buy_price",
        "spread",
        "investment",
        "profit",
        "isk_per_hour",
        "total_return_pct",
        "wallet_return_pct",
        "sell_order_id",
        "buy_order_id",
    ])?;
    for row in rows {
        writer.write_record([
            format_ts(row.snapshot_ts),
            format_ts(row.arrival_ts),
            if row.arrival_snapshot_ts == NO_SNAPSHOT_TS {
                String::new()
            } else {
                format_ts(row.arrival_snapshot_ts)
            },
            row.type_id.to_string(),
            row.from_system.to_string(),
            row.to_system.to_string(),
            row.gate_jumps.to_string(),
            row.route_seconds.to_string(),
            (row.route_seconds as f64 / 60.0).to_string(),
            (row.can_take_advantage != 0).to_string(),
            row.quantity.to_string(),
            row.sell_price.to_string(),
            row.buy_price.to_string(),
            (row.buy_price - row.sell_price).to_string(),
            row.investment.to_string(),
            row.profit.to_string(),
            row.isk_per_hour.to_string(),
            row.total_return_pct.to_string(),
            row.wallet_return_pct.to_string(),
            row.sell_order_id.to_string(),
            row.buy_order_id.to_string(),
        ])?;
    }
    writer.flush()?;
    Ok(())
}

fn snapshot_ts_from_path(path: &Path) -> Option<i64> {
    let filename = path.file_name()?.to_str()?;
    let prefix = "market-orders-";
    let start = filename.find(prefix)? + prefix.len();
    let stamp = filename.get(start..start + 19)?;
    let naive = NaiveDateTime::parse_from_str(stamp, "%Y-%m-%d_%H-%M-%S").ok()?;
    Some(naive.and_utc().timestamp())
}

fn format_ts(ts: i64) -> String {
    DateTime::<Utc>::from_timestamp(ts, 0)
        .map(|dt| dt.to_rfc3339())
        .unwrap_or_default()
}

fn parse<T>(value: Option<&str>, column: &str) -> Result<T>
where
    T: std::str::FromStr,
    T::Err: std::error::Error + Send + Sync + 'static,
{
    value
        .ok_or_else(|| anyhow!("missing value for {column}"))?
        .parse()
        .with_context(|| format!("invalid value for {column}"))
}

fn cmp_f64_asc(a: f64, b: f64) -> Ordering {
    a.partial_cmp(&b).unwrap_or(Ordering::Equal)
}

fn cmp_f64_desc(a: f64, b: f64) -> Ordering {
    b.partial_cmp(&a).unwrap_or(Ordering::Equal)
}
