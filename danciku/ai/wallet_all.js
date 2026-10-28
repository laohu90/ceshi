const {
  mnemonicToSeedSync,
  HDKey,
  createPublicClient,
  http,
  formatEther
} = require('viem');

// 你的助记词
const mnemonic = 'auction soon wheel inject picnic cup where popular risk safe victory atom';

// 各链 RPC
const chainList = [
  { name: 'ETH 以太坊', rpc: 'https://rpc.ethereum.org' },
  { name: 'BNB BSC', rpc: 'https://bsc-dataseed1.binance.org' },
  { name: 'Base', rpc: 'https://mainnet.base.org' },
  { name: 'Linea', rpc: 'https://rpc.linea.build' },
  { name: 'Polygon', rpc: 'https://polygon-rpc.com' },
  { name: 'Monad', rpc: 'https://rpc.monad.xyz' },
  { name: 'Optimism OP', rpc: 'https://mainnet.optimism.io' },
  { name: 'Arbitrum ARB', rpc: 'https://arb1.arbitrum.io/rpc' }
];

// 公钥转 EVM 地址
function pubToAddress(pubHex) {
  const { keccak256, toBytes } = require('viem');
  const pubBytes = toBytes(pubHex, 'hex').slice(1);
  const hash = keccak256(pubBytes);
  return '0x' + hash.slice(-40);
}

(async () => {
  // 推导地址、私钥
  const seed = mnemonicToSeedSync(mnemonic);
  const master = HDKey.fromMasterSeed(seed);
  const child = master.derive("m/44'/60'/0'/0/0");

  const address = pubToAddress(child.publicKey.toString('hex'));
  const privateKey = '0x' + child.privateKey.toString('hex');

  const wallet = { address, privateKey };
  const balances = [];

  // 批量查余额
  for (const item of chainList) {
    try {
      const client = createPublicClient({ transport: http(item.rpc) });
      const bal = await client.getBalance({ address });
      balances.push({
        chain: item.name,
        balance: formatEther(bal)
      });
    } catch (e) {
      balances.push({
        chain: item.name,
        balance: '查询失败'
      });
    }
  }

  const result = { wallet, balances };
  console.log(JSON.stringify(result));
})();