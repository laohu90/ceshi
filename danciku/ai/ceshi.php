<?php
// 钱包地址
$wallet = "0x48eE5d85e239c95F96d0aB19880BEefB5D0452a7";

// 更换为亚太/全球稳定RPC，日本服务器优先连通
$chains = [
    '以太坊 ETH' => [
        ['https://eth.llamarpc.com', 18],
        ['https://rpc.ethereum.org', 18],
        ['https://ethereum.publicnode.com', 18]
    ],
    '币安智能链 BNB' => [
        ['https://bsc-dataseed1.binance.org', 18],
        ['https://bsc-dataseed3.binance.org', 18],
        ['https://bsc.publicnode.com', 18]
    ],
    'Base' => [
        ['https://base.llamarpc.com', 18],
        ['https://mainnet.base.org', 18]
    ],
    'Linea' => [
        ['https://linea.llamarpc.com', 18],
        ['https://rpc.linea.build', 18]
    ],
    'Polygon MATIC' => [
        ['https://polygon.llamarpc.com', 18],
        ['https://matic-mainnet.chainstacklabs.com', 18],
        ['https://matic.publicnode.com', 18]
    ],
    'Optimism OP' => [
        ['https://optimism.llamarpc.com', 18],
        ['https://mainnet.optimism.io', 18]
    ],
    'Arbitrum ARB' => [
        ['https://arbitrum.llamarpc.com', 18],
        ['https://arb1.arbitrum.io/rpc', 18]
    ],
    'Monad' => [
        ['https://testnet-rpc.monad.xyz', 18],
        ['https://monad-testnet.rpc.guru', 18]
    ]
];

// ERC20 代币配置 (合约+小数位)
$tokens = [
    '币安智能链 BNB' => [
        ['BSC-USDT', '0x55d398326f99059fF775485246999027B3197955f', 18]
    ],
    '以太坊 ETH' => [
        ['ETH-USDT', '0xdAC17F958D2ee523a2206206994597C13D831ec7', 6]
    ]
];

/**
 * 16进制转10进制（超大数兼容）
 */
function hexToDec(string $hex): string
{
    $hex = strtolower(trim($hex));
    $len = strlen($hex);
    $dec = '0';
    for ($i = 0; $i < $len; $i++) {
        $char = $hex[$i];
        $val  = ctype_digit($char) ? $char : (ord($char) - ord('a') + 10);
        $dec  = bcmul($dec, '16');
        $dec  = bcadd($dec, $val);
    }
    return $dec;
}

/**
 * 通用RPC请求
 */
function rpcRequest(string $rpcUrl, array $postData): ?string
{
    $postStr = json_encode($postData);
    $ch = curl_init($rpcUrl);
    curl_setopt_array($ch, [
        CURLOPT_POST           => true,
        CURLOPT_POSTFIELDS     => $postStr,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT        => 15,
        CURLOPT_CONNECTTIMEOUT => 8,
        CURLOPT_SSL_VERIFYPEER => false,
        CURLOPT_SSL_VERIFYHOST => false,
        CURLOPT_HTTPHEADER     => [
            'Content-Type: application/json',
            'User-Agent: Mozilla/5.0'
        ]
    ]);

    $resp = curl_exec($ch);
    $curlErr = curl_error($ch);
    curl_close($ch);

    if (!empty($curlErr) || empty($resp)) return null;
    $data = json_decode($resp, true);
    if (json_last_error() !== JSON_ERROR_NONE || isset($data['error'])) return null;
    return $data['result'] ?? null;
}

/**
 * 多节点轮询 查询原生主币
 */
function getNativeBalance(array $rpcList, string $address, int $decimals): string
{
    foreach ($rpcList as $item) {
        list($rpc) = $item;
        $post = [
            "jsonrpc" => "2.0",
            "method"  => "eth_getBalance",
            "params"  => [$address, "latest"],
            "id"      => 1
        ];
        $hexWei = rpcRequest($rpc, $post);
        if ($hexWei === null) continue;

        $hexWei = ltrim($hexWei, '0x');
        $hexWei = $hexWei === '' ? '0' : $hexWei;
        $wei = hexToDec($hexWei);
        $div = bcpow('10', (string)$decimals);
        return bcdiv($wei, $div, 8);
    }
    return "节点全部请求失败";
}

/**
 * 多节点轮询 查询ERC20代币
 */
function getTokenBalance(array $rpcList, string $address, string $tokenContract, int $decimals): string
{
    $data = '0x70a08231' . str_pad(ltrim($address, '0x'), 64, '0', STR_PAD_LEFT);
    foreach ($rpcList as $item) {
        list($rpc) = $item;
        $post = [
            "jsonrpc" => "2.0",
            "method"  => "eth_call",
            "params"  => [
                ["to" => $tokenContract, "data" => $data],
                "latest"
            ],
            "id" => 1
        ];
        $hexWei = rpcRequest($rpc, $post);
        if ($hexWei === null) continue;

        $hexWei = ltrim($hexWei, '0x');
        $hexWei = $hexWei === '' ? '0' : $hexWei;
        $wei = hexToDec($hexWei);
        $div = bcpow('10', (string)$decimals);
        return bcdiv($wei, $div, 8);
    }
    return "节点全部请求失败";
}

// 输出
echo "钱包地址：{$wallet}\n";
echo "========================================\n";

foreach ($chains as $chainName => $rpcList) {
    $mainDec = $rpcList[0][1];
    $mainBal = getNativeBalance($rpcList, $wallet, $mainDec);
    echo sprintf("%-16s 主币: %s\n", $chainName, $mainBal);

    if (isset($tokens[$chainName])) {
        foreach ($tokens[$chainName] as $token) {
            list($tokenName, $contract, $tokenDec) = $token;
            $tokenBal = getTokenBalance($rpcList, $wallet, $contract, $tokenDec);
            echo sprintf("  %-14s: %s\n", $tokenName, $tokenBal);
        }
    }
    echo "----------------------------------------\n";
}
?>