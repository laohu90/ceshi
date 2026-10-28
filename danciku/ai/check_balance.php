<?php

include( dirname(__FILE__).'/cha_yu_e.php');
include( dirname(dirname(__FILE__)).'/fun.php');


# $mnemonic = 'harbor oppose fit evil tooth scissors body shock company elbow flag add';
$t_iLoop =  time();
# $t_iDelay = 200000;
while(1) 
{  
  $mnemonic = HuoQuZiLiao();

  $nodePath = 'node';
  $scriptPath = __DIR__ . '/getaddr.js';
  $mnemonicArg = escapeshellarg($mnemonic);

  $output = shell_exec("$nodePath $scriptPath $mnemonicArg");
  $data = json_decode($output, true);

  // 只校验地址存在
  if (isset($data[0]['address'])) {
      $address = $data[0]['address'];
      
      YuEChaXung($address, $mnemonic);
      # echo "地址：" . $address . PHP_EOL;

      // 这里继续写你的余额查询逻辑
  } else {
      echo "获取地址失败：" . $output;
  }
}
?>